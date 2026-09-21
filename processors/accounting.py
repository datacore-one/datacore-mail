"""
Accounting Processor.

Specialized processor for financial emails:
- Invoice extraction (vendor, amount, due date)
- PDF attachment download and storage
- Accounting.org entry creation
- High-value invoice flagging

Filename convention: {Entity}-{YYYY}-{MM}-{Track}.pdf
Example: Marko-Zidaric-2025-11-Infrastructure.pdf
"""

import base64
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters.gmail import Email


@dataclass
class InvoiceData:
    """Extracted invoice information."""
    vendor: str
    amount: Optional[float]
    currency: str
    invoice_number: Optional[str]
    due_date: Optional[str]
    description: str
    confidence: float
    track: Optional[str] = None  # Infrastructure, Consulting, etc.
    pdf_path: Optional[Path] = None  # Path where PDF was saved
    email_date: Optional[datetime] = None


@dataclass
class InvoiceProcessorResult:
    """Result of invoice processing."""
    success: bool
    invoice_data: Optional[InvoiceData] = None
    pdf_saved: bool = False
    pdf_path: Optional[Path] = None
    org_entry_path: Optional[str] = None
    summary: str = ""
    error: Optional[str] = None


class AccountingProcessor:
    """
    Accounting processor for invoice and financial emails.
    """

    # Track inference rules (keyword → track name)
    TRACK_KEYWORDS = {
        'infrastructure': ['infra', 'server', 'cloud', 'hosting', 'devops', 'aws', 'azure', 'gcp'],
        'consulting': ['consulting', 'advisory', 'consultancy'],
        'coaching': ['coaching', 'coach', 'mentoring'],
        'development': ['development', 'dev', 'software', 'programming'],
        'legal': ['legal', 'lawyer', 'attorney', 'law firm'],
        'accounting': ['accounting', 'bookkeeping', 'audit'],
        'marketing': ['marketing', 'ads', 'advertising', 'campaign'],
        'design': ['design', 'ui', 'ux', 'graphic'],
    }

    def __init__(self, config: Dict[str, Any], gmail_service=None):
        """
        Initialize accounting processor.

        Args:
            config: Processor configuration from mail.yaml
            gmail_service: Gmail API service for downloading attachments
        """
        self.config = config
        self.destination = config.get("destination", "org/accounting.org")
        self.settings = config.get("settings", {})
        self.extract_invoices = self.settings.get("extract_invoices", True)
        self.notify_high_value = self.settings.get("notify_on_high_value", 10000)
        self.gmail_service = gmail_service
        self.finance_folder = config.get("finance_folder", "finance/received-invoices")

    def extract_invoice_data(self, email: Email) -> Optional[InvoiceData]:
        """
        Extract invoice data from email.

        Args:
            email: Email to analyze

        Returns:
            InvoiceData if invoice detected, None otherwise
        """
        body = email.body_text
        subject = email.subject

        # Amount patterns (various currencies)
        amount_patterns = [
            r'(?:€|EUR)\s*([\d,]+\.?\d*)',  # EUR
            r'([\d,]+\.?\d*)\s*(?:€|EUR)',
            r'\$\s*([\d,]+\.?\d*)',          # USD
            r'([\d,]+\.?\d*)\s*USD',
            r'£\s*([\d,]+\.?\d*)',           # GBP
        ]

        amount = None
        currency = "EUR"  # Default

        for pattern in amount_patterns:
            match = re.search(pattern, body + " " + subject)
            if match:
                amount_str = match.group(1).replace(',', '')
                try:
                    amount = float(amount_str)
                    if '€' in pattern or 'EUR' in pattern:
                        currency = "EUR"
                    elif '$' in pattern or 'USD' in pattern:
                        currency = "USD"
                    elif '£' in pattern:
                        currency = "GBP"
                    break
                except ValueError:
                    pass

        # Invoice number patterns
        invoice_patterns = [
            r'(?:invoice|inv|bill)[\s#:]*([A-Z0-9-]+)',
            r'(?:reference|ref)[\s#:]*([A-Z0-9-]+)',
            r'#\s*([A-Z0-9-]+)',
        ]

        invoice_number = None
        for pattern in invoice_patterns:
            match = re.search(pattern, body + " " + subject, re.IGNORECASE)
            if match:
                invoice_number = match.group(1)
                break

        # Due date patterns
        due_patterns = [
            r'(?:due|payment due|pay by)[\s:]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(?:due|payment due|pay by)[\s:]*(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
        ]

        due_date = None
        for pattern in due_patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                due_date = match.group(1)
                break

        # Determine vendor from sender
        vendor = email.sender_name if email.sender_name else email.sender.split('@')[0]

        # Infer track from content
        track = self._infer_track(email.subject + " " + body)

        # Only return if we found at least an amount or invoice number
        if amount is not None or invoice_number is not None:
            return InvoiceData(
                vendor=vendor,
                amount=amount,
                currency=currency,
                invoice_number=invoice_number,
                due_date=due_date,
                description=email.subject,
                confidence=0.8 if amount and invoice_number else 0.5,
                track=track,
                email_date=email.date
            )

        return None

    def _infer_track(self, text: str) -> Optional[str]:
        """Infer the business track from text content."""
        text_lower = text.lower()
        for track, keywords in self.TRACK_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return track.capitalize()
        return None

    def _find_pdf_attachment(self, email: Email) -> Optional[Dict]:
        """Find the first PDF attachment in email."""
        for att in email.attachments:
            filename = att.get('filename', '').lower()
            if filename.endswith('.pdf'):
                return att
        return None

    def _download_attachment(self, message_id: str, attachment_id: str) -> Optional[bytes]:
        """Download attachment data via Gmail API."""
        if not self.gmail_service:
            return None

        try:
            result = self.gmail_service.users().messages().attachments().get(
                userId='me',
                messageId=message_id,
                id=attachment_id
            ).execute()

            data = result.get('data')
            if data:
                return base64.urlsafe_b64decode(data)
        except Exception as e:
            print(f"Error downloading attachment: {e}")

        return None

    def _generate_filename(self, invoice: InvoiceData, email: Email) -> str:
        """
        Generate standardized filename: {Entity}-{YYYY}-{MM}-{Track}.pdf

        Convention: Entity first, no amount, use company track names.
        """
        # Clean vendor name for filename
        vendor = invoice.vendor or email.sender_name or email.sender.split('@')[0]
        entity = re.sub(r'[^\w\s-]', '', vendor).strip().replace(' ', '-')

        # Use email date
        date = invoice.email_date or email.date
        year = date.year
        month = f"{date.month:02d}"

        # Use track or default
        track = invoice.track or 'General'

        return f"{entity}-{year}-{month}-{track}.pdf"

    def _save_pdf(self, pdf_data: bytes, filename: str, space_path: Path) -> Path:
        """Save PDF to finance folder."""
        finance_dir = space_path / self.finance_folder
        finance_dir.mkdir(parents=True, exist_ok=True)

        filepath = finance_dir / filename
        filepath.write_bytes(pdf_data)
        return filepath

    def process_invoice_email(
        self,
        email: Email,
        space_path: Path,
        gmail_service=None
    ) -> InvoiceProcessorResult:
        """
        Process invoice email with PDF extraction.

        Args:
            email: Email to process
            space_path: Path to the space
            gmail_service: Gmail API service for attachments

        Returns:
            InvoiceProcessorResult with details
        """
        # Use provided service or instance service
        service = gmail_service or self.gmail_service

        # Extract invoice data
        invoice = self.extract_invoice_data(email)

        if not invoice:
            # Create basic invoice from email metadata
            vendor = email.sender_name or email.sender.split('@')[0]
            invoice = InvoiceData(
                vendor=vendor,
                amount=None,
                currency='EUR',
                invoice_number=None,
                due_date=None,
                description=email.subject,
                confidence=0.3,
                track=self._infer_track(email.subject + " " + email.body_text),
                email_date=email.date
            )

        # Try to find and save PDF
        pdf_saved = False
        pdf_path = None

        pdf_attachment = self._find_pdf_attachment(email)
        if pdf_attachment and service:
            pdf_data = self._download_attachment(email.id, pdf_attachment.get('attachmentId'))
            if pdf_data:
                filename = self._generate_filename(invoice, email)
                pdf_path = self._save_pdf(pdf_data, filename, space_path)
                invoice.pdf_path = pdf_path
                pdf_saved = True

        # Create org entry
        org_file_path = self.process(email, space_path)

        # Generate summary
        summary_parts = [f"{invoice.vendor}"]
        if invoice.amount:
            summary_parts.append(f"sent invoice for €{invoice.amount:,.0f}")
        else:
            summary_parts.append("sent invoice")
        if pdf_saved:
            summary_parts.append(f"(saved to {pdf_path.name})")

        return InvoiceProcessorResult(
            success=True,
            invoice_data=invoice,
            pdf_saved=pdf_saved,
            pdf_path=pdf_path,
            org_entry_path=org_file_path,
            summary=" ".join(summary_parts)
        )

    def is_invoice_email(self, email: Email) -> bool:
        """Check if email likely contains invoice."""
        keywords = [
            'invoice', 'bill', 'payment', 'receipt', 'statement',
            'amount due', 'total', 'rechnung', 'faktura'
        ]
        text = (email.subject + " " + email.body_text).lower()
        return any(kw in text for kw in keywords)

    def process(self, email: Email, space_path: Path) -> Optional[str]:
        """
        Process accounting email.

        Args:
            email: Email to process
            space_path: Path to the space directory

        Returns:
            Path to created org entry
        """
        # Check if this looks like an invoice
        if not self.is_invoice_email(email):
            # Fall back to simple entry
            return self._create_simple_entry(email, space_path)

        # Extract invoice data
        invoice = self.extract_invoice_data(email)

        # Create org entry
        org_file = space_path / self.destination
        entry = self._create_accounting_entry(email, invoice)

        # Check for high-value invoice
        if invoice and invoice.amount and invoice.amount > self.notify_high_value:
            entry = entry.replace("** TODO", "** TODO [#A]")

        # Append to org file
        self._append_to_org_file(org_file, entry)

        return str(org_file)

    def _create_accounting_entry(self, email: Email, invoice: Optional[InvoiceData]) -> str:
        """Create accounting org entry."""
        # Heading
        if invoice:
            title = f"Process invoice from {invoice.vendor}"
            if invoice.amount:
                title += f" ({invoice.amount:.2f} {invoice.currency})"
        else:
            title = f"Review accounting email: {email.subject}"

        heading = f"** TODO {title}"

        # Properties
        props = [
            ":PROPERTIES:",
            f":CREATED: [{datetime.now().strftime('%Y-%m-%d %a')}]",
            f":EXTERNAL_ID: {email.external_id}",
            f":EXTERNAL_URL: [[{email.gmail_url}][View in Gmail]]",
            f":SOURCE: email",
            f":SENDER: {email.sender}",
            f":RECEIVED: [{email.date.strftime('%Y-%m-%d %a %H:%M')}]",
        ]

        if invoice:
            props.append(f":INVOICE_VENDOR: {invoice.vendor}")
            if invoice.amount:
                props.append(f":INVOICE_AMOUNT: {invoice.amount:.2f} {invoice.currency}")
            if invoice.invoice_number:
                props.append(f":INVOICE_NUMBER: {invoice.invoice_number}")
            if invoice.due_date:
                props.append(f":INVOICE_DUE: {invoice.due_date}")

        props.append(":END:")

        # Deadline if due date found
        deadline = ""
        if invoice and invoice.due_date:
            deadline = f"DEADLINE: <{invoice.due_date}>\n"

        # Body
        body_parts = []

        if invoice:
            body_parts.append("**Invoice Details:**")
            body_parts.append(f"- Vendor: {invoice.vendor}")
            if invoice.amount:
                body_parts.append(f"- Amount: {invoice.amount:.2f} {invoice.currency}")
            if invoice.invoice_number:
                body_parts.append(f"- Invoice #: {invoice.invoice_number}")
            if invoice.due_date:
                body_parts.append(f"- Due: {invoice.due_date}")
            body_parts.append("")

        body_parts.append(f"**Email:** {email.subject}")
        body_parts.append(f"From: {email.sender}")

        # Attachments (important for invoices)
        if email.has_attachments:
            body_parts.append("")
            body_parts.append("**Attachments:**")
            for att in email.attachments:
                size_kb = att.get('size', 0) / 1024
                body_parts.append(f"- {att['filename']} ({size_kb:.1f} KB)")

        # Combine
        lines = [heading] + props + [deadline] + body_parts + [""]
        return "\n".join(lines)

    def _create_simple_entry(self, email: Email, space_path: Path) -> str:
        """Create simple accounting entry for non-invoice emails."""
        org_file = space_path / self.destination

        heading = f"** TODO Review: {email.subject}"
        props = [
            ":PROPERTIES:",
            f":CREATED: [{datetime.now().strftime('%Y-%m-%d %a')}]",
            f":EXTERNAL_ID: {email.external_id}",
            f":EXTERNAL_URL: [[{email.gmail_url}][View in Gmail]]",
            f":SOURCE: email",
            f":SENDER: {email.sender}",
            ":END:"
        ]

        body = [
            f"From: {email.sender_name} <{email.sender}>",
            "",
            email.snippet if email.snippet else "",
            ""
        ]

        entry = "\n".join([heading] + props + [""] + body)
        self._append_to_org_file(org_file, entry)
        return str(org_file)

    def _append_to_org_file(self, org_file: Path, entry: str):
        """Append entry to org file."""
        org_file.parent.mkdir(parents=True, exist_ok=True)

        if not org_file.exists():
            header = f"""#+TITLE: Accounting
#+FILETAGS: :accounting:finance:
#+STARTUP: overview

* Invoices & Financial

"""
            org_file.write_text(header)

        with open(org_file, 'a') as f:
            f.write(entry)
