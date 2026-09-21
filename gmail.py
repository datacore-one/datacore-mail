"""
Gmail Adapter for Mail Module.

Handles Gmail API interactions for pulling, sending, and managing emails.

Usage:
    from mail.adapters.gmail import GmailAdapter

    adapter = GmailAdapter({"address": "victor@example.com"})
    if adapter.is_configured():
        emails = adapter.pull_emails(days=7)
"""

import base64
import hashlib
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Any, Dict, List, Optional

# Credentials directory
CREDS_DIR = Path(__file__).parent.parent.parent.parent / "env" / "credentials"

# Gmail API scopes
# Note: mail.google.com gives full access including permanent delete
SCOPES = [
    'https://mail.google.com/',  # Full access (needed for permanent delete)
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
]

# Use same client secret as calendar adapter
CLIENT_SECRETS_FILE = CREDS_DIR / "google_calendar_client_secret.json"


@dataclass
class Email:
    """Represents an email message."""
    id: str
    thread_id: str
    subject: str
    sender: str
    sender_name: str
    recipients: List[str]
    date: datetime
    snippet: str

    # Content
    body_text: str = ""
    body_html: str = ""

    # Metadata
    labels: List[str] = field(default_factory=list)
    is_unread: bool = True
    is_starred: bool = False
    has_attachments: bool = False
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    # Threading
    in_reply_to: Optional[str] = None
    references: List[str] = field(default_factory=list)

    # GitHub notification reason (X-GitHub-Reason header).
    # Values used by GitHub: review_requested, mention, comment, assign,
    # author, subscribed, manual, team_mention, your_activity, push,
    # security_advisory, ci_activity. Used by the classifier to route
    # github notifications via the events config instead of subject
    # keyword matching (which never matches because GitHub subjects mirror
    # issue/PR titles, not event types).
    gh_reason: Optional[str] = None

    # Raw data
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def external_id(self) -> str:
        """Generate external ID for org-mode linking."""
        return f"gmail:{self.sender}/{self.id}"

    @property
    def gmail_url(self) -> str:
        """URL to view email in Gmail web."""
        return f"https://mail.google.com/mail/u/0/#inbox/{self.id}"


class GmailAdapter:
    """
    Gmail adapter for the mail module.

    Handles OAuth authentication, email fetching, sending, and status updates.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Gmail adapter.

        Args:
            config: Account configuration from mail.yaml
                - address: Email address
                - labels: List of labels to sync (default: ["INBOX"])
        """
        self.address = config.get("address", "")
        self.labels = config.get("labels", ["INBOX"])
        self.config = config

        self._service = None
        self._credentials = None

    @property
    def name(self) -> str:
        return "gmail"

    @property
    def token_file(self) -> Path:
        """Per-account token file."""
        # Hash the email address for filename safety
        addr_hash = hashlib.md5(self.address.encode()).hexdigest()[:8]
        return CREDS_DIR / f"gmail_token_{addr_hash}.pickle"

    @property
    def client_secrets_file(self) -> Path:
        """OAuth client secrets file (shared with calendar adapter)."""
        return CLIENT_SECRETS_FILE

    def is_configured(self) -> bool:
        """Check if adapter is properly configured."""
        return self.client_secrets_file.exists() and self.token_file.exists()

    def test_connection(self) -> tuple[bool, str]:
        """Test connection to Gmail API."""
        try:
            service = self._get_service()
            if not service:
                return False, f"Could not connect to Gmail for {self.address}"

            # Try to get profile
            profile = service.users().getProfile(userId='me').execute()
            email = profile.get('emailAddress', 'unknown')
            return True, f"Connected to: {email}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def _get_credentials(self):
        """Get valid user credentials."""
        if self._credentials:
            return self._credentials

        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = None

        if self.token_file.exists():
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed token
                with open(self.token_file, 'wb') as token:
                    pickle.dump(creds, token)
            else:
                return None

        self._credentials = creds
        return creds

    def _get_service(self):
        """Get Gmail API service."""
        if self._service:
            return self._service

        creds = self._get_credentials()
        if not creds:
            return None

        from googleapiclient.discovery import build
        self._service = build('gmail', 'v1', credentials=creds)
        return self._service

    def setup_auth(self) -> bool:
        """
        Run OAuth flow for first-time setup.

        Returns:
            True if authentication successful.
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.client_secrets_file.exists():
            print(f"ERROR: Client secrets file not found at {self.client_secrets_file}")
            print("\nTo set up Gmail access:")
            print("1. Go to https://console.cloud.google.com/")
            print("2. Enable 'Gmail API'")
            print("3. Go to Credentials → Create OAuth 2.0 Client ID")
            print("4. Choose 'Desktop app' as application type")
            print("5. Download the JSON and save it as:")
            print(f"   {self.client_secrets_file}")
            return False

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets_file), SCOPES)
        creds = flow.run_local_server(port=0)

        # Save credentials
        CREDS_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.token_file, 'wb') as token:
            pickle.dump(creds, token)

        print(f"Credentials saved to {self.token_file}")
        return True

    # =========================================================================
    # Pull Emails
    # =========================================================================

    def pull_emails(
        self,
        labels: List[str] = None,
        query: str = None,
        days: int = 7,
        max_results: int = 50,
        unread_only: bool = False
    ) -> List[Email]:
        """
        Pull emails from Gmail with full pagination support.

        Args:
            labels: Gmail labels to filter (default: configured labels)
            query: Additional Gmail search query
            days: Number of days to look back
            max_results: Maximum emails to return (0 = unlimited)
            unread_only: Only return unread emails

        Returns:
            List of Email objects
        """
        service = self._get_service()
        if not service:
            return []

        emails = []
        labels = self.labels if labels is None else labels

        # Build query
        q_parts = []

        if days:
            after_date = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
            q_parts.append(f"after:{after_date}")

        if unread_only:
            q_parts.append("is:unread")

        if query:
            q_parts.append(query)

        query_string = " ".join(q_parts) if q_parts else None

        try:
            # Get label IDs
            label_ids = []
            if labels:
                labels_result = service.users().labels().list(userId='me').execute()
                label_map = {l['name']: l['id'] for l in labels_result.get('labels', [])}
                label_ids = [label_map.get(l, l) for l in labels]

            # List messages with pagination
            all_message_refs = []
            page_token = None

            while True:
                # API max is 500 per page
                page_size = min(500, max_results - len(all_message_refs)) if max_results else 500

                results = service.users().messages().list(
                    userId='me',
                    labelIds=label_ids if label_ids else None,
                    q=query_string,
                    maxResults=page_size,
                    pageToken=page_token
                ).execute()

                messages = results.get('messages', [])
                all_message_refs.extend(messages)

                page_token = results.get('nextPageToken')

                # Stop if no more pages or reached max_results
                if not page_token:
                    break
                if max_results and len(all_message_refs) >= max_results:
                    break

            # Fetch full details for each message
            for msg_ref in all_message_refs:
                msg = service.users().messages().get(
                    userId='me',
                    id=msg_ref['id'],
                    format='full'
                ).execute()

                email = self._parse_message(msg)
                emails.append(email)

        except Exception as e:
            print(f"Error pulling emails: {e}")

        return emails

    def list_message_ids(
        self,
        query: str = None,
        labels: List[str] = None,
        max_results: int = 0
    ) -> List[str]:
        """
        List all message IDs matching query (fast, no content fetch).

        Args:
            query: Gmail search query
            labels: Labels to filter by
            max_results: Maximum IDs to return (0 = unlimited)

        Returns:
            List of message IDs
        """
        service = self._get_service()
        if not service:
            return []

        message_ids = []
        page_token = None
        # Use explicit None check - empty list means no label filter
        if labels is None:
            labels = self.labels

        try:
            # Get label IDs (empty labels = no filter)
            label_ids = []
            if labels:
                labels_result = service.users().labels().list(userId='me').execute()
                label_map = {l['name']: l['id'] for l in labels_result.get('labels', [])}
                label_ids = [label_map.get(l, l) for l in labels]

            while True:
                page_size = min(500, max_results - len(message_ids)) if max_results else 500

                results = service.users().messages().list(
                    userId='me',
                    labelIds=label_ids if label_ids else None,
                    q=query,
                    maxResults=page_size,
                    pageToken=page_token
                ).execute()

                for msg in results.get('messages', []):
                    message_ids.append(msg['id'])

                page_token = results.get('nextPageToken')

                if not page_token:
                    break
                if max_results and len(message_ids) >= max_results:
                    break

        except Exception as e:
            print(f"Error listing message IDs: {e}")

        return message_ids

    def get_message_metadata(
        self,
        message_id: str,
        headers: List[str] = None
    ) -> Dict[str, Any]:
        """
        Get message metadata only (headers, no body).

        Args:
            message_id: Gmail message ID
            headers: List of headers to fetch (default: From, To, Subject, Date)

        Returns:
            Dict with id, threadId, and requested headers
        """
        service = self._get_service()
        if not service:
            return {}

        headers = headers or ['From', 'To', 'Subject', 'Date']

        try:
            msg = service.users().messages().get(
                userId='me',
                id=message_id,
                format='metadata',
                metadataHeaders=headers
            ).execute()

            result = {
                'id': msg['id'],
                'threadId': msg.get('threadId', ''),
                'labelIds': msg.get('labelIds', []),
                'snippet': msg.get('snippet', '')
            }

            # Parse headers
            for header in msg.get('payload', {}).get('headers', []):
                result[header['name'].lower()] = header['value']

            return result

        except Exception as e:
            print(f"Error getting message metadata: {e}")
            return {}

    def get_all_senders(
        self,
        query: str = None,
        labels: List[str] = None,
        max_results: int = 0,
        progress_callback=None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract all unique senders from emails (metadata-only, efficient).

        Args:
            query: Gmail search query (e.g., "in:all" for all mail)
            labels: Labels to filter by
            max_results: Maximum emails to scan (0 = unlimited)
            progress_callback: Optional callback(current, total) for progress

        Returns:
            Dict mapping sender email to stats:
            {
                "sender@example.com": {
                    "name": "Sender Name",
                    "count": 42,
                    "last_date": "2025-12-22",
                    "sample_subjects": ["Subject 1", "Subject 2"]
                }
            }
        """
        service = self._get_service()
        if not service:
            return {}

        # Step 1: Get all message IDs
        message_ids = self.list_message_ids(query=query, labels=labels, max_results=max_results)
        total = len(message_ids)

        if progress_callback:
            progress_callback(0, total)

        # Step 2: Fetch metadata for each message
        senders: Dict[str, Dict[str, Any]] = {}

        for i, msg_id in enumerate(message_ids):
            metadata = self.get_message_metadata(msg_id, ['From', 'Subject', 'Date'])

            if metadata:
                from_header = metadata.get('from', '')
                sender_name, sender_email = self._parse_email_address(from_header)
                sender_email = sender_email.lower()

                if sender_email:
                    if sender_email not in senders:
                        senders[sender_email] = {
                            'name': sender_name,
                            'count': 0,
                            'last_date': '',
                            'sample_subjects': []
                        }

                    senders[sender_email]['count'] += 1

                    # Update name if we have a better one
                    if sender_name and not senders[sender_email]['name']:
                        senders[sender_email]['name'] = sender_name

                    # Track last date
                    date_str = metadata.get('date', '')
                    if date_str:
                        senders[sender_email]['last_date'] = date_str

                    # Sample subjects (first 3)
                    subject = metadata.get('subject', '')
                    if subject and len(senders[sender_email]['sample_subjects']) < 3:
                        senders[sender_email]['sample_subjects'].append(subject)

            if progress_callback and (i + 1) % 100 == 0:
                progress_callback(i + 1, total)

        if progress_callback:
            progress_callback(total, total)

        return senders

    def get_all_contacts(
        self,
        query: str = None,
        labels: List[str] = None,
        max_results: int = 0,
        progress_callback=None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract all unique email addresses (senders AND recipients).

        Returns:
            Dict mapping email to stats:
            {
                "contact@example.com": {
                    "name": "Contact Name",
                    "sent_count": 5,      # Emails I sent to them
                    "received_count": 10,  # Emails I received from them
                    "last_date": "2025-12-22"
                }
            }
        """
        service = self._get_service()
        if not service:
            return {}

        message_ids = self.list_message_ids(query=query, labels=labels, max_results=max_results)
        total = len(message_ids)

        if progress_callback:
            progress_callback(0, total)

        contacts: Dict[str, Dict[str, Any]] = {}
        my_email = self.address.lower()

        for i, msg_id in enumerate(message_ids):
            metadata = self.get_message_metadata(msg_id, ['From', 'To', 'Date'])

            if metadata:
                from_header = metadata.get('from', '')
                to_header = metadata.get('to', '')
                date_str = metadata.get('date', '')

                sender_name, sender_email = self._parse_email_address(from_header)
                sender_email = sender_email.lower()

                # Parse recipients
                recipients = self._parse_email_list(to_header)

                # Determine if this is sent or received
                is_sent = sender_email == my_email

                if is_sent:
                    # I sent this - track recipients
                    for recipient in recipients:
                        _, recip_email = self._parse_email_address(recipient)
                        recip_email = recip_email.lower()
                        if recip_email and recip_email != my_email:
                            if recip_email not in contacts:
                                contacts[recip_email] = {
                                    'name': '',
                                    'sent_count': 0,
                                    'received_count': 0,
                                    'last_date': ''
                                }
                            contacts[recip_email]['sent_count'] += 1
                            contacts[recip_email]['last_date'] = date_str
                else:
                    # I received this - track sender
                    if sender_email and sender_email != my_email:
                        if sender_email not in contacts:
                            contacts[sender_email] = {
                                'name': sender_name,
                                'sent_count': 0,
                                'received_count': 0,
                                'last_date': ''
                            }
                        contacts[sender_email]['received_count'] += 1
                        if sender_name:
                            contacts[sender_email]['name'] = sender_name
                        contacts[sender_email]['last_date'] = date_str

            if progress_callback and (i + 1) % 100 == 0:
                progress_callback(i + 1, total)

        if progress_callback:
            progress_callback(total, total)

        return contacts

    def _parse_message(self, msg: Dict) -> Email:
        """Parse Gmail API message to Email object."""
        headers = {}
        for header in msg.get('payload', {}).get('headers', []):
            headers[header['name'].lower()] = header['value']

        # Parse sender
        from_header = headers.get('from', '')
        sender_name, sender = self._parse_email_address(from_header)

        # Parse recipients
        to_header = headers.get('to', '')
        recipients = self._parse_email_list(to_header)

        # Parse date
        date_str = headers.get('date', '')
        email_date = self._parse_date(date_str)

        # Get body
        body_text, body_html = self._extract_body(msg.get('payload', {}))

        # Get attachments
        attachments = self._extract_attachments(msg.get('payload', {}))

        # Labels
        label_ids = msg.get('labelIds', [])

        return Email(
            id=msg['id'],
            thread_id=msg.get('threadId', ''),
            subject=headers.get('subject', 'No Subject'),
            sender=sender,
            sender_name=sender_name,
            recipients=recipients,
            date=email_date,
            snippet=msg.get('snippet', ''),
            body_text=body_text,
            body_html=body_html,
            labels=label_ids,
            is_unread='UNREAD' in label_ids,
            is_starred='STARRED' in label_ids,
            has_attachments=len(attachments) > 0,
            attachments=attachments,
            in_reply_to=headers.get('in-reply-to'),
            references=headers.get('references', '').split(),
            gh_reason=headers.get('x-github-reason'),
            raw=msg
        )

    def _parse_email_address(self, addr: str) -> tuple[str, str]:
        """Parse 'Name <email@example.com>' format."""
        import re
        match = re.match(r'"?([^"<]*)"?\s*<?([^>]*)>?', addr)
        if match:
            name = match.group(1).strip()
            email = match.group(2).strip() or addr
            return name, email
        return '', addr

    def _parse_email_list(self, header: str) -> List[str]:
        """Parse comma-separated email list."""
        if not header:
            return []
        return [e.strip() for e in header.split(',')]

    def _parse_date(self, date_str: str) -> datetime:
        """Parse email date header."""
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.now()

    def _extract_body(self, payload: Dict) -> tuple[str, str]:
        """Extract text and HTML body from message payload."""
        text_body = ""
        html_body = ""

        def extract_parts(part):
            nonlocal text_body, html_body

            mime_type = part.get('mimeType', '')
            body_data = part.get('body', {}).get('data', '')

            if body_data:
                content = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                if mime_type == 'text/plain':
                    text_body = content
                elif mime_type == 'text/html':
                    html_body = content

            for sub_part in part.get('parts', []):
                extract_parts(sub_part)

        extract_parts(payload)
        return text_body, html_body

    def _extract_attachments(self, payload: Dict) -> List[Dict]:
        """Extract attachment info from message payload."""
        attachments = []

        def extract_parts(part):
            filename = part.get('filename', '')
            if filename:
                attachments.append({
                    'filename': filename,
                    'mimeType': part.get('mimeType', ''),
                    'size': part.get('body', {}).get('size', 0),
                    'attachmentId': part.get('body', {}).get('attachmentId', '')
                })

            for sub_part in part.get('parts', []):
                extract_parts(sub_part)

        extract_parts(payload)
        return attachments

    # =========================================================================
    # Send Emails
    # =========================================================================

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: List[str] = None,
        bcc: List[str] = None,
        reply_to: str = None,
        attachments: List[Path] = None
    ) -> Optional[str]:
        """
        Send an email via Gmail API.

        Args:
            to: Recipient email addresses
            subject: Email subject
            body: Email body (plain text)
            cc: CC recipients
            bcc: BCC recipients
            reply_to: In-Reply-To header for threading
            attachments: List of file paths to attach

        Returns:
            Message ID if successful, None otherwise.
        """
        service = self._get_service()
        if not service:
            return None

        # Create message
        if attachments:
            message = MIMEMultipart()
            message.attach(MIMEText(body, 'plain'))

            for file_path in attachments:
                with open(file_path, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{file_path.name}"'
                )
                message.attach(part)
        else:
            message = MIMEText(body, 'plain')

        message['to'] = ', '.join(to)
        message['subject'] = subject

        if cc:
            message['cc'] = ', '.join(cc)
        if reply_to:
            message['In-Reply-To'] = reply_to
            message['References'] = reply_to

        # Encode and send
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        try:
            sent = service.users().messages().send(
                userId='me',
                body={'raw': raw}
            ).execute()

            return sent.get('id')
        except Exception as e:
            print(f"Error sending email: {e}")
            return None

    def reply(
        self,
        thread_id: str,
        message_id: str,
        body: str,
        to: List[str] = None
    ) -> Optional[str]:
        """
        Reply to an email thread.

        Args:
            thread_id: Gmail thread ID
            message_id: Original message ID (for In-Reply-To)
            body: Reply body
            to: Override recipients (default: reply to sender)

        Returns:
            Message ID if successful.
        """
        # Get original message for headers
        service = self._get_service()
        if not service:
            return None

        try:
            original = service.users().messages().get(
                userId='me',
                id=message_id,
                format='metadata',
                metadataHeaders=['From', 'Subject']
            ).execute()

            headers = {h['name']: h['value'] for h in original.get('payload', {}).get('headers', [])}

            # Build reply
            subject = headers.get('Subject', '')
            if not subject.lower().startswith('re:'):
                subject = f"Re: {subject}"

            to_addr = to or [headers.get('From', '')]

            return self.send_email(
                to=to_addr,
                subject=subject,
                body=body,
                reply_to=message_id
            )
        except Exception as e:
            print(f"Error replying to email: {e}")
            return None

    # =========================================================================
    # Status Updates
    # =========================================================================

    def archive(self, message_id: str) -> bool:
        """Archive email (remove INBOX label), and record that it happened.

        The record is written HERE rather than in the scanner because this is
        the chokepoint every caller passes through, including an agent calling
        `adapter.archive()` on its own initiative. Before 2026-09-17 the only
        mail log was run-level totals, so "what happened to this email?" had no
        answer at all.
        """
        service = self._get_service()
        if not service:
            self._record_disposition(message_id, 'archive', False, error='not configured')
            return False

        try:
            service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['INBOX']}
            ).execute()
            self._record_disposition(message_id, 'archive', True)
            return True
        except Exception as e:
            print(f"Error archiving email: {e}")
            self._record_disposition(message_id, 'archive', False, error=type(e).__name__)
            return False

    def _record_disposition(self, message_id: str, action: str, ok: bool, **extra) -> None:
        """One line per message, per disposition. Never raises, never blocks."""
        try:
            from mail_audit import record
        except ImportError:
            try:
                import sys as _sys
                from pathlib import Path as _Path
                _sys.path.insert(0, str(_Path(__file__).resolve().parent))
                from mail_audit import record
            except Exception:  # noqa: BLE001
                return
        account = ''
        try:
            account = (self.config or {}).get('address', '') or ''
        except Exception:  # noqa: BLE001
            pass
        meta = {}
        try:
            cached = getattr(self, '_message_meta', {}).get(message_id) or {}
            meta = {'sender': cached.get('sender'), 'subject': cached.get('subject')}
        except Exception:  # noqa: BLE001
            pass
        record(account, message_id, action, ok, **{**meta, **extra})

    def add_label(self, message_id: str, label: str) -> bool:
        """Add label to email."""
        service = self._get_service()
        if not service:
            return False

        try:
            # Get or create label
            label_id = self._get_or_create_label(label)

            service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'addLabelIds': [label_id]}
            ).execute()
            return True
        except Exception as e:
            print(f"Error labeling email: {e}")
            return False

    def mark_read(self, message_id: str) -> bool:
        """Mark email as read."""
        service = self._get_service()
        if not service:
            return False

        try:
            service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error marking email as read: {e}")
            return False

    def mark_processed(self, message_id: str, label: str = "datacore/processed") -> bool:
        """Mark email as processed by Datacore."""
        return self.add_label(message_id, label)

    def trash(self, message_id: str) -> bool:
        """Move email to trash — REFUSED unless explicitly enabled.

        Gmail purges Trash after 30 days, so trashing correspondence is a
        deferred deletion, not a filing decision. Triage archives: the mail
        leaves the inbox, stays in All Mail, and stays searchable for ever.

        This is refused rather than merely discouraged because nothing in this
        codebase calls it, while the `/mails` command used to list "Trash
        emails" as a permitted action — so the only thing standing between an
        agent and a 30-day fuse was a sentence in a prompt. Correspondence was
        lost that way (2026-09-17). An instruction is not a control.

        Set DATACORE_MAIL_ALLOW_TRASH=1 for a deliberate, supervised cleanup.
        """
        import os
        if os.environ.get('DATACORE_MAIL_ALLOW_TRASH') != '1':
            print('Refusing to trash mail: triage archives, it does not delete. '
                  'Set DATACORE_MAIL_ALLOW_TRASH=1 for a supervised cleanup.')
            self._record_disposition(message_id, 'trash', False, error='refused by policy')
            return False
        service = self._get_service()
        if not service:
            return False
        try:
            service.users().messages().trash(userId='me', id=message_id).execute()
            return True
        except Exception as e:
            print(f"Error trashing email: {e}")
            return False

    def delete(self, message_id: str) -> bool:
        """Permanently delete email — ALWAYS REFUSED.

        Immediate and unrecoverable: not the Trash, no 30-day window, no undo.
        Nothing in this codebase calls it and nothing should. Kept as a
        refusing stub rather than removed so that a caller written against the
        old contract fails loudly instead of resolving to some other `delete`.

        Archiving is the disposition for everything, including spam.
        """
        print('Refusing to permanently delete mail. Archive instead; '
              'permanent deletion is not available to automation.')
        self._record_disposition(message_id, 'delete', False, error='refused by policy')
        return False

    def _unreachable_delete(self, message_id: str) -> bool:
        service = self._get_service()
        if not service:
            return False
        try:
            service.users().messages().delete(userId='me', id=message_id).execute()
            return True
        except Exception as e:
            print(f"Error deleting email: {e}")
            return False

    def _get_or_create_label(self, label_name: str) -> str:
        """Get label ID, creating if it doesn't exist."""
        service = self._get_service()

        # Check if label exists
        labels_result = service.users().labels().list(userId='me').execute()
        for label in labels_result.get('labels', []):
            if label['name'] == label_name:
                return label['id']

        # Create label
        new_label = service.users().labels().create(
            userId='me',
            body={
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
        ).execute()

        return new_label['id']


# =============================================================================
# CLI Interface
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Gmail Adapter")
    parser.add_argument("command", choices=["setup", "test", "pull", "send"],
                       help="Command to run")
    parser.add_argument("--account", required=True,
                       help="Email account address")
    parser.add_argument("--days", type=int, default=7,
                       help="Days to look back")
    parser.add_argument("--max", type=int, default=10,
                       help="Max results")
    parser.add_argument("--unread", action="store_true",
                       help="Only unread emails")
    parser.add_argument("--to", help="Recipient for send")
    parser.add_argument("--subject", help="Subject for send")
    parser.add_argument("--body", help="Body for send")

    args = parser.parse_args()

    adapter = GmailAdapter({"address": args.account})

    if args.command == "setup":
        print(f"Setting up Gmail authentication for {args.account}...")
        if adapter.setup_auth():
            print("\nAuthentication complete!")
        else:
            print("\nAuthentication failed.")

    elif args.command == "test":
        success, message = adapter.test_connection()
        print(f"{'✓' if success else '✗'} {message}")

    elif args.command == "pull":
        if not adapter.is_configured():
            print(f"Account not configured. Run: python gmail.py setup --account {args.account}")
        else:
            emails = adapter.pull_emails(
                days=args.days,
                max_results=args.max,
                unread_only=args.unread
            )
            print(f"\nFound {len(emails)} emails:\n")
            for email in emails:
                status = "●" if email.is_unread else "○"
                print(f"  {status} {email.date.strftime('%Y-%m-%d %H:%M')} | {email.sender_name or email.sender}")
                print(f"    {email.subject}")
                if email.has_attachments:
                    print(f"    📎 {len(email.attachments)} attachment(s)")
                print()

    elif args.command == "send":
        if not all([args.to, args.subject, args.body]):
            print("Send requires --to, --subject, and --body")
        else:
            msg_id = adapter.send_email(
                to=[args.to],
                subject=args.subject,
                body=args.body
            )
            if msg_id:
                print(f"✓ Email sent (ID: {msg_id})")
            else:
                print("✗ Failed to send email")
