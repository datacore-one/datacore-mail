"""
Mail Module Coordinator.

Loads mail.yaml from spaces and orchestrates email processing.
"""

import yaml
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters import get_adapter
from .processors import get_processor
from .processors.classifier import ClassifierProcessor, batch_classify, batch_process, quick_classify
from .processors.github import GitHubProcessor, update_org_task
from .processors.accounting import AccountingProcessor
from .processors.newsletter import NewsletterProcessor, batch_process_newsletters


@dataclass
class AccountConfig:
    """Configuration for a single email account."""
    name: str
    address: str
    provider: str
    processor: str
    destination: str
    labels: List[str]
    settings: Dict[str, Any]
    space_path: Path


@dataclass
class ProcessingResult:
    """Result of processing an email account."""
    account: str
    space: str
    emails_processed: int
    emails_ignored: int
    entries_created: List[str]
    errors: List[str]


class MailModule:
    """
    Mail module coordinator.

    Discovers mail.yaml files in spaces and processes emails.
    """

    def __init__(self, data_root: Path = None):
        """
        Initialize mail module.

        Args:
            data_root: Root data directory (default: ~/Data)
        """
        self.data_root = data_root or Path.home() / "Data"
        self.accounts: List[AccountConfig] = []

    def discover_configs(self) -> List[AccountConfig]:
        """
        Discover mail.yaml files in all spaces.

        Returns:
            List of account configurations
        """
        accounts = []

        # Find all space directories (0-*, 1-*, etc.)
        for space_dir in sorted(self.data_root.iterdir()):
            if not space_dir.is_dir():
                continue
            if not space_dir.name[0].isdigit():
                continue

            mail_yaml = space_dir / ".datacore" / "mail.yaml"
            if mail_yaml.exists():
                space_accounts = self._load_space_config(mail_yaml, space_dir)
                accounts.extend(space_accounts)

        self.accounts = accounts
        return accounts

    def _load_space_config(self, mail_yaml: Path, space_dir: Path) -> List[AccountConfig]:
        """Load accounts from a space's mail.yaml."""
        accounts = []

        try:
            with open(mail_yaml) as f:
                config = yaml.safe_load(f) or {}

            for acc in config.get("accounts", []):
                account = AccountConfig(
                    name=acc.get("name", "default"),
                    address=acc.get("address", ""),
                    provider=acc.get("provider", "gmail"),
                    processor=acc.get("processor", "classifier"),
                    destination=acc.get("destination", "org/inbox.org"),
                    labels=acc.get("labels", ["INBOX"]),
                    settings=acc.get("settings", {}),
                    space_path=space_dir
                )
                accounts.append(account)

        except Exception as e:
            print(f"Error loading {mail_yaml}: {e}")

        return accounts

    def get_adapter_for_account(self, account: AccountConfig):
        """Get configured adapter for account."""
        adapter_class = get_adapter(account.provider)
        return adapter_class({
            "address": account.address,
            "labels": account.labels,
            **account.settings
        })

    def get_processor_for_account(self, account: AccountConfig, gmail_service=None):
        """Get configured processor for account."""
        processor_class = get_processor(account.processor)

        # Handle special cases for processors that need extra params
        if account.processor == 'github':
            return processor_class(
                space_path=account.space_path,
                org_files=['org/next_actions.org', 'org/inbox.org']
            )
        elif account.processor == 'accounting':
            return processor_class(
                {
                    "destination": account.destination,
                    **account.settings
                },
                gmail_service=gmail_service
            )
        else:
            return processor_class(
                {
                    "destination": account.destination,
                    "address": account.address,
                    **account.settings
                },
                space_path=account.space_path
            )

    def process_account(
        self,
        account: AccountConfig,
        days: int = 7,
        max_emails: int = 50,
        dry_run: bool = False
    ) -> ProcessingResult:
        """
        Process emails for a single account.

        Uses two-stage processing:
        1. Classifier determines action level and tracks
        2. If classifier routes to specialized processor (github, accounting),
           use that processor instead

        Args:
            account: Account configuration
            days: Number of days to look back
            max_emails: Maximum emails to process
            dry_run: If True, don't create entries or mark processed

        Returns:
            Processing result
        """
        result = ProcessingResult(
            account=account.name,
            space=account.space_path.name,
            emails_processed=0,
            emails_ignored=0,
            entries_created=[],
            errors=[]
        )

        try:
            # Get adapter
            adapter = self.get_adapter_for_account(account)

            # Check if configured
            if not adapter.is_configured():
                result.errors.append(f"Account not configured: {account.address}")
                return result

            # Pull emails
            emails = adapter.pull_emails(
                labels=account.labels,
                days=days,
                max_results=max_emails,
                unread_only=True
            )

            # Initialize processors (lazy)
            classifier = ClassifierProcessor(
                {"destination": account.destination, "address": account.address},
                space_path=account.space_path
            )
            github_processor = None
            accounting_processor = None

            for email in emails:
                try:
                    # Stage 1: Classify email
                    classification = classifier.classify(email)

                    # Stage 2: Route to specialized processor if needed
                    entry_path = None

                    if classification.processor == 'github':
                        # Route to GitHub processor
                        if github_processor is None:
                            github_processor = GitHubProcessor(
                                space_path=account.space_path,
                                org_files=['org/next_actions.org', 'org/inbox.org']
                            )

                        gh_result = github_processor.process(email)

                        # Handle GitHub result
                        if gh_result.action == 'UPDATE_TASK' and gh_result.linked_task:
                            if not dry_run:
                                update_org_task(gh_result.linked_task, 'DONE')
                                adapter.archive(email.id)
                            result.emails_processed += 1
                            result.entries_created.append(f"Updated task: {gh_result.summary}")
                        elif gh_result.action == 'REPLY_NEEDED':
                            # Create inbox entry for manual handling
                            entry_path = classifier.process(email, account.space_path)
                            if entry_path:
                                result.entries_created.append(entry_path)
                                result.emails_processed += 1
                        else:
                            # ARCHIVE_ONLY
                            if not dry_run:
                                adapter.archive(email.id)
                            result.emails_ignored += 1
                        continue

                    elif classification.processor == 'accounting':
                        # Route to accounting processor
                        if accounting_processor is None:
                            accounting_processor = AccountingProcessor(
                                {"destination": account.destination, **account.settings},
                                gmail_service=adapter._service
                            )

                        acc_result = accounting_processor.process_invoice_email(
                            email, account.space_path, gmail_service=adapter._service
                        )

                        if acc_result.success:
                            result.entries_created.append(acc_result.summary)
                            result.emails_processed += 1
                            if not dry_run:
                                adapter.archive(email.id)
                        else:
                            result.errors.append(acc_result.error or "Unknown accounting error")
                        continue

                    # Standard processing path
                    if classification.action in ('ACTIONABLE',):
                        entry_path = classifier.process(email, account.space_path)

                    if entry_path:
                        result.entries_created.append(entry_path)
                        result.emails_processed += 1

                        if not dry_run:
                            adapter.mark_processed(email.id)
                    else:
                        result.emails_ignored += 1

                        if not dry_run and account.processor == "archive":
                            adapter.archive(email.id)

                except Exception as e:
                    result.errors.append(f"Error processing email {email.id}: {e}")

        except Exception as e:
            result.errors.append(f"Error with account {account.name}: {e}")

        return result

    def scan_all(
        self,
        days: int = 7,
        max_emails: int = 50,
        dry_run: bool = False
    ) -> List[ProcessingResult]:
        """
        Scan all configured accounts.

        Args:
            days: Number of days to look back
            max_emails: Maximum emails per account
            dry_run: If True, don't create entries or mark processed

        Returns:
            List of processing results
        """
        if not self.accounts:
            self.discover_configs()

        results = []
        for account in self.accounts:
            print(f"Processing {account.name} ({account.address}) in {account.space_path.name}...")
            result = self.process_account(account, days, max_emails, dry_run)
            results.append(result)

            # Print summary
            print(f"  Processed: {result.emails_processed}, Ignored: {result.emails_ignored}")
            if result.errors:
                for error in result.errors:
                    print(f"  ERROR: {error}")

        return results

    def scan_space(
        self,
        space_name: str,
        days: int = 7,
        max_emails: int = 50,
        dry_run: bool = False
    ) -> List[ProcessingResult]:
        """
        Scan accounts for a specific space.

        Args:
            space_name: Space directory name (e.g., "1-teamspace")
            days: Number of days to look back
            max_emails: Maximum emails per account
            dry_run: If True, don't create entries or mark processed

        Returns:
            List of processing results
        """
        if not self.accounts:
            self.discover_configs()

        results = []
        for account in self.accounts:
            if account.space_path.name == space_name:
                result = self.process_account(account, days, max_emails, dry_run)
                results.append(result)

        return results

    def process_newsletters(
        self,
        account: AccountConfig,
        days: int = 7,
        max_emails: int = 100,
        category: str = None,
        dry_run: bool = False,
        execute: bool = False
    ) -> Dict:
        """
        Batch process newsletter emails.

        Args:
            account: Account configuration
            days: Number of days to look back
            max_emails: Maximum emails to process
            category: Filter by category (RESEARCH, PRODUCT_UPDATE, DAILY_NEWS, etc.)
            dry_run: Show what would happen without making changes
            execute: Actually process and archive emails

        Returns:
            Dict with processing summary
        """
        results = {
            'account': account.name,
            'space': account.space_path.name,
            'total_emails': 0,
            'by_category': {},
            'processed': [],
            'errors': []
        }

        try:
            # Get adapter and pull emails
            adapter = self.get_adapter_for_account(account)
            if not adapter.is_configured():
                results['errors'].append(f"Account not configured: {account.address}")
                return results

            emails = adapter.pull_emails(
                labels=account.labels,
                days=days,
                max_results=max_emails
            )
            results['total_emails'] = len(emails)

            # Classify all emails
            classifications = batch_classify(
                emails,
                {'destination': account.destination, 'address': account.address},
                space_path=account.space_path
            )

            # Count by category
            category_counts = {
                'RESEARCH': 0,
                'PRODUCT_UPDATE': 0,
                'DAILY_NEWS': 0,
                'COMPETITOR': 0,
                'SPAM': 0,
                'OTHER': 0
            }

            # Get INFORMATIONAL emails (newsletters)
            informational = classifications.get('INFORMATIONAL', [])

            # Build email lookup
            email_map = {e.id: e for e in emails}

            # Process each newsletter
            processor = NewsletterProcessor(
                account.space_path,
                gmail_service=adapter._service if hasattr(adapter, '_service') else None
            )

            for classification in informational:
                email_id = classification.get('external_id', '').split('/')[-1]
                email = email_map.get(email_id)
                if not email:
                    continue

                # Determine category
                action = classification.get('action', 'archive_only')
                nl_type = classification.get('type', '')

                if action == 'prepare_for_research':
                    cat = 'RESEARCH'
                elif action == 'check_product_update':
                    cat = 'PRODUCT_UPDATE'
                elif nl_type == 'daily_news':
                    cat = 'DAILY_NEWS'
                elif nl_type == 'competitor':
                    cat = 'COMPETITOR'
                elif nl_type == 'spam':
                    cat = 'SPAM'
                else:
                    cat = 'OTHER'

                category_counts[cat] += 1

                # Skip if filtering by category
                if category and cat != category.upper():
                    continue

                # Process based on mode
                if dry_run:
                    results['processed'].append({
                        'action': 'DRY_RUN',
                        'category': cat,
                        'subject': email.subject[:50],
                        'would_do': action
                    })
                elif execute:
                    try:
                        result = processor.process(email, classification)
                        results['processed'].append({
                            'action': result.action,
                            'category': result.category,
                            'subject': email.subject[:50],
                            'summary': result.summary
                        })

                        # The processor only REQUESTS archival; we perform it.
                        if result.should_archive:
                            adapter.archive(email.id)

                    except Exception as e:
                        results['errors'].append(f"Error processing {email.id}: {e}")

            results['by_category'] = category_counts

        except Exception as e:
            results['errors'].append(f"Error: {e}")

        return results

    def newsletter_stats(
        self,
        account: AccountConfig,
        days: int = 30
    ) -> Dict:
        """
        Get newsletter statistics for an account.

        Args:
            account: Account configuration
            days: Number of days to analyze

        Returns:
            Dict with newsletter statistics
        """
        stats = {
            'account': account.name,
            'days': days,
            'total': 0,
            'by_category': {},
            'by_sender': {},
            'by_action': {}
        }

        try:
            adapter = self.get_adapter_for_account(account)
            if not adapter.is_configured():
                return stats

            emails = adapter.pull_emails(
                labels=account.labels,
                days=days,
                max_results=200
            )

            classifications = batch_classify(
                emails,
                {'destination': account.destination, 'address': account.address},
                space_path=account.space_path
            )

            informational = classifications.get('INFORMATIONAL', [])
            stats['total'] = len(informational)

            for c in informational:
                # By category
                action = c.get('action', 'archive_only')
                nl_type = c.get('type', 'other')

                if action == 'prepare_for_research':
                    cat = 'RESEARCH'
                elif action == 'check_product_update':
                    cat = 'PRODUCT_UPDATE'
                else:
                    cat = nl_type.upper() if nl_type else 'OTHER'

                stats['by_category'][cat] = stats['by_category'].get(cat, 0) + 1

                # By sender
                sender = c.get('sender', 'unknown')
                stats['by_sender'][sender] = stats['by_sender'].get(sender, 0) + 1

                # By action
                stats['by_action'][action] = stats['by_action'].get(action, 0) + 1

        except Exception as e:
            stats['error'] = str(e)

        return stats

    # =========================================================================
    # Interactive Processing Methods (for /mails command)
    # =========================================================================

    def get_grouped_emails(
        self,
        account: AccountConfig,
        days: int = 7,
        max_emails: int = 100
    ) -> Dict:
        """
        Pull, classify, and group emails for interactive processing.

        Returns dict with:
        - emails: List of Email objects
        - classifications: Dict of classification results by group
        - cc_groups: CC emails grouped by processor type
        - info_groups: INFORMATIONAL emails grouped by newsletter type
        - action_groups: ACTIONABLE emails grouped by sender
        - spam: SPAM emails (for auto-archive)
        """
        adapter = self.get_adapter_for_account(account)
        if not adapter.is_configured():
            return {'error': f"Account not configured: {account.address}"}

        emails = adapter.pull_emails(
            labels=account.labels,
            days=days,
            max_results=max_emails
        )

        classifications = batch_classify(
            emails,
            {'destination': account.destination, 'address': account.address},
            space_path=account.space_path
        )

        # Build email lookup
        email_map = {e.id: e for e in emails}

        return {
            'emails': emails,
            'email_map': email_map,
            'classifications': classifications,
            'cc_groups': self._group_by_processor(classifications.get('CC', []), email_map),
            'info_groups': self._group_by_newsletter_type(classifications.get('INFORMATIONAL', []), email_map),
            'action_groups': self._group_by_sender(classifications.get('ACTIONABLE', []), email_map),
            'spam': classifications.get('SPAM', [])
        }

    def _group_by_processor(self, items: List[Dict], email_map: Dict) -> Dict:
        """Group CC emails by their designated processor."""
        groups = {
            'github': [],
            'accounting': [],
            'archive': []
        }

        for item in items:
            processor = item.get('processor', 'archive')
            email_id = item.get('external_id', '').split('/')[-1]
            email = email_map.get(email_id)

            if processor == 'github':
                groups['github'].append({'item': item, 'email': email})
            elif processor == 'accounting':
                groups['accounting'].append({'item': item, 'email': email})
            else:
                groups['archive'].append({'item': item, 'email': email})

        return groups

    def _group_by_newsletter_type(self, items: List[Dict], email_map: Dict) -> Dict:
        """Group INFORMATIONAL emails by newsletter type/action."""
        groups = {
            'research': [],      # prepare_for_research
            'daily_news': [],    # aggregate_daily_news
            'product': [],       # check_product_update
            'competitor': [],    # competitor intel
            'archive': []        # archive_only
        }

        for item in items:
            action = item.get('action', 'archive_only')
            nl_type = item.get('type', '')
            email_id = item.get('external_id', '').split('/')[-1]
            email = email_map.get(email_id)

            entry = {'item': item, 'email': email}

            if action == 'prepare_for_research':
                groups['research'].append(entry)
            elif action == 'aggregate_daily_news' or nl_type == 'daily_news':
                groups['daily_news'].append(entry)
            elif action == 'check_product_update' or nl_type == 'product_update':
                groups['product'].append(entry)
            elif nl_type == 'competitor':
                groups['competitor'].append(entry)
            else:
                groups['archive'].append(entry)

        return groups

    def _group_by_sender(self, items: List[Dict], email_map: Dict) -> Dict:
        """Group ACTIONABLE emails by sender for efficient review."""
        groups = {}

        for item in items:
            email_id = item.get('external_id', '').split('/')[-1]
            email = email_map.get(email_id)
            if not email:
                continue

            # Normalize sender for grouping
            sender_key = self._normalize_sender(email.sender, email.sender_name)

            if sender_key not in groups:
                groups[sender_key] = {
                    'sender': email.sender,
                    'sender_name': email.sender_name,
                    'emails': [],
                    'context': item.get('matched_rule', 'unknown')
                }

            groups[sender_key]['emails'].append({'item': item, 'email': email})

        return groups

    def _normalize_sender(self, sender_email: str, sender_name: str = None) -> str:
        """Normalize sender for grouping (e.g., multiple emails from same person)."""
        # Use domain + first part of name if available
        if sender_name:
            name_parts = sender_name.lower().split()
            if name_parts:
                return name_parts[0]

        # Fall back to email domain
        if '@' in sender_email:
            domain = sender_email.split('@')[1].lower()
            # Strip common suffixes
            for suffix in ['.com', '.io', '.co', '.org', '.net']:
                domain = domain.replace(suffix, '')
            return domain

        return sender_email.lower()

    def execute_group_action(
        self,
        account: AccountConfig,
        emails: List,
        action: str,
        options: Dict = None
    ) -> List[Dict]:
        """
        Execute action on a group of emails.

        Actions:
        - archive: Mark read and archive
        - create_task: Write to inbox.org
        - create_crm: Write CRM note to 3-knowledge/pages/
        - aggregate_daily: Create single daily digest task
        """
        adapter = self.get_adapter_for_account(account)
        results = []
        options = options or {}

        for email_data in emails:
            email = email_data.get('email')
            item = email_data.get('item', {})

            if not email:
                continue

            try:
                if action == 'archive':
                    adapter.mark_read(email.id)
                    adapter.archive(email.id)
                    results.append({'email_id': email.id, 'action': 'archived', 'success': True})

                elif action == 'create_task':
                    # Write task to inbox.org
                    task_entry = self._generate_task_entry(email, item, options)
                    inbox_path = account.space_path / 'org/inbox.org'
                    self._append_to_inbox(inbox_path, task_entry)
                    adapter.mark_read(email.id)
                    adapter.archive(email.id)
                    results.append({'email_id': email.id, 'action': 'task_created', 'success': True})

                elif action == 'create_crm':
                    # Write CRM note
                    org_name = options.get('organization', 'Unknown')
                    crm_content = self._generate_crm_note(email, item, options)
                    crm_path = account.space_path / f'3-knowledge/pages/General Contact - {org_name}.md'
                    crm_path.write_text(crm_content)
                    results.append({'email_id': email.id, 'action': 'crm_created', 'path': str(crm_path), 'success': True})

            except Exception as e:
                results.append({'email_id': email.id, 'action': action, 'success': False, 'error': str(e)})

        return results

    def _generate_task_entry(self, email, item: Dict, options: Dict) -> str:
        """Generate org-mode task entry for email."""
        from datetime import datetime

        tags = options.get('tags', [])
        tag_str = ':' + ':'.join(tags) + ':' if tags else ''
        scheduled = options.get('scheduled', '')
        scheduled_str = f"\nSCHEDULED: <{scheduled}>" if scheduled else ''

        today = datetime.now().strftime("%Y-%m-%d %a")
        gmail_url = f"https://mail.google.com/mail/u/0/#inbox/{email.id}"

        subject = email.subject[:60] + '...' if len(email.subject) > 60 else email.subject
        default_verb = 'Research' if item.get('action') == 'prepare_for_research' else 'Follow up on'
        action_verb = options.get('action_verb', default_verb)

        return f"""** TODO {action_verb}: {subject} {tag_str}{scheduled_str}
:PROPERTIES:
:CREATED: [{today}]
:EXTERNAL_URL: [[{gmail_url}][Email]]
:END:

From: {email.sender_name or email.sender}
Date: {email.date.strftime('%Y-%m-%d')}

{options.get('context', '')}
"""

    def _generate_crm_note(self, email, item: Dict, options: Dict) -> str:
        """Generate CRM note for new contact."""
        from datetime import datetime

        org_name = options.get('organization', 'Unknown')
        contact_name = email.sender_name or email.sender.split('@')[0]
        tags = options.get('tags', ['contact'])
        today = datetime.now().strftime('%Y-%m-%d')

        return f"""---
aliases:
  - {org_name}
type: organization
organization: {org_name}
contact: {contact_name}
contact_email: {email.sender}
contact_status: Active
tags:
  - {chr(10) + '  - '.join(tags)}
created: {today}
---

# {org_name}

## Overview

{options.get('description', '[To be filled]')}

## Key Contact

| Name | Email | Notes |
|------|-------|-------|
| {contact_name} | {email.sender} | Initial contact |

## Interaction Log

| Date | Type | Summary |
|------|------|---------|
| {today} | Email | {email.subject[:50]} |

## Next Actions

- [ ] {options.get('next_action', 'Follow up')}
"""

    def _append_to_inbox(self, inbox_path: Path, entry: str):
        """Append entry to inbox.org after * Inbox heading."""
        if not inbox_path.exists():
            return

        content = inbox_path.read_text()
        insert_marker = "* Inbox\n"
        insert_pos = content.find(insert_marker)

        if insert_pos >= 0:
            insert_pos += len(insert_marker)
            new_content = content[:insert_pos] + "\n" + entry + content[insert_pos:]
            inbox_path.write_text(new_content)


# =============================================================================
# CLI Interface
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mail Module")
    parser.add_argument("command", choices=["discover", "scan", "status", "newsletters", "stats"],
                       help="Command to run")
    parser.add_argument("--space", help="Specific space to process")
    parser.add_argument("--account", help="Specific account name")
    parser.add_argument("--days", type=int, default=7, help="Days to look back")
    parser.add_argument("--max", type=int, default=50, help="Max emails per account")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--execute", action="store_true", help="Actually process and archive")
    parser.add_argument("--category", help="Filter by category (RESEARCH, PRODUCT_UPDATE, etc.)")
    parser.add_argument("--data-root", type=Path, help="Data root directory")

    args = parser.parse_args()

    module = MailModule(data_root=args.data_root)

    if args.command == "discover":
        accounts = module.discover_configs()
        print(f"\nFound {len(accounts)} account(s):\n")
        for acc in accounts:
            print(f"  {acc.space_path.name}/{acc.name}")
            print(f"    Address: {acc.address}")
            print(f"    Processor: {acc.processor}")
            print(f"    Destination: {acc.destination}")
            print()

    elif args.command == "scan":
        if args.space:
            results = module.scan_space(args.space, args.days, args.max, args.dry_run)
        else:
            results = module.scan_all(args.days, args.max, args.dry_run)

        print("\n=== Scan Complete ===")
        total_processed = sum(r.emails_processed for r in results)
        total_ignored = sum(r.emails_ignored for r in results)
        total_errors = sum(len(r.errors) for r in results)
        print(f"Total: {total_processed} processed, {total_ignored} ignored, {total_errors} errors")

    elif args.command == "status":
        accounts = module.discover_configs()
        print(f"\n=== Mail Module Status ===\n")
        for acc in accounts:
            adapter = module.get_adapter_for_account(acc)
            configured = "✓" if adapter.is_configured() else "✗"
            print(f"{configured} {acc.space_path.name}/{acc.name}: {acc.address}")

    elif args.command == "newsletters":
        accounts = module.discover_configs()

        # Find matching account(s)
        target_accounts = []
        for acc in accounts:
            if args.space and acc.space_path.name != args.space:
                continue
            if args.account and acc.name != args.account:
                continue
            target_accounts.append(acc)

        if not target_accounts:
            print("No matching accounts found. Use --space or --account to filter.")
            exit(1)

        print(f"\n=== Newsletter Processing ===\n")

        for acc in target_accounts:
            print(f"Processing {acc.space_path.name}/{acc.name} ({acc.address})...")

            result = module.process_newsletters(
                acc,
                days=args.days,
                max_emails=args.max,
                category=args.category,
                dry_run=args.dry_run,
                execute=args.execute
            )

            # Print summary
            print(f"\n  Total emails scanned: {result['total_emails']}")
            print(f"  Newsletter breakdown:")
            for cat, count in sorted(result['by_category'].items()):
                if count > 0:
                    print(f"    {cat}: {count}")

            if result['processed']:
                print(f"\n  Processed {len(result['processed'])} email(s):")
                for p in result['processed'][:10]:  # Show first 10
                    status = "✓" if p['action'] != 'ERROR' else "✗"
                    print(f"    {status} [{p['category']}] {p['subject']}")
                if len(result['processed']) > 10:
                    print(f"    ... and {len(result['processed']) - 10} more")

            if result['errors']:
                print(f"\n  Errors:")
                for err in result['errors']:
                    print(f"    ✗ {err}")

            if not args.dry_run and not args.execute:
                print(f"\n  (Use --dry-run to preview or --execute to process)")

    elif args.command == "stats":
        accounts = module.discover_configs()

        # Find matching account(s)
        target_accounts = []
        for acc in accounts:
            if args.space and acc.space_path.name != args.space:
                continue
            if args.account and acc.name != args.account:
                continue
            target_accounts.append(acc)

        if not target_accounts:
            print("No matching accounts found.")
            exit(1)

        print(f"\n=== Newsletter Statistics (last {args.days} days) ===\n")

        for acc in target_accounts:
            stats = module.newsletter_stats(acc, days=args.days)

            print(f"{acc.space_path.name}/{acc.name}: {stats['total']} newsletters")

            if stats['by_category']:
                print(f"  By category:")
                for cat, count in sorted(stats['by_category'].items(), key=lambda x: -x[1]):
                    print(f"    {cat}: {count}")

            if stats['by_sender']:
                print(f"  Top senders:")
                top_senders = sorted(stats['by_sender'].items(), key=lambda x: -x[1])[:5]
                for sender, count in top_senders:
                    print(f"    {sender}: {count}")

            print()
