"""
Classifier Processor.

Two-dimensional email classification using layered rules (DIP-0002 pattern):
- Action Level: ACTIONABLE, INFORMATIONAL, CC, SPAM
- Track: BUSINESS, RESEARCH, NEWSLETTER, GITHUB, FINANCE, CALENDAR

Rules are merged: base → space → local (later wins)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

from ..adapters.gmail import Email


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Classification:
    """Result of email classification."""
    action: str  # ACTIONABLE, INFORMATIONAL, CC, SPAM, GITHUB
    tracks: List[str]  # BUSINESS, RESEARCH, NEWSLETTER, etc.
    confidence: float
    actions: List[str]
    priority: str  # HIGH, MEDIUM, LOW
    effort: str  # Quick, Moderate, Significant
    suggested_title: str
    deadline: Optional[str]
    reasoning: str
    age_days: int = 0
    is_stale: bool = False
    matched_rules: List[str] = field(default_factory=list)  # Which rules triggered
    processor: Optional[str] = None  # Route to specialized processor: 'github', 'accounting', None
    newsletter_action: Optional[str] = None  # Newsletter rule action: prepare_for_research, aggregate_daily_news, etc.
    newsletter_rule: Optional[Dict] = None  # Full matched newsletter/research rule config
    event_passed: bool = False  # For calendar emails: event has already occurred
    event_date: Optional[str] = None  # Detected event date (YYYY-MM-DD)


@dataclass
class MergedRules:
    """Merged rules from all layers."""
    senders_actionable: List[Dict]
    senders_research: List[Dict]
    senders_newsletter: List[Dict]
    senders_api_cost_providers: List[Dict]
    senders_ignore: List[Dict]
    subjects_calendar: List[Dict]
    subjects_finance: List[Dict]
    body_newsletter: List[Dict]
    domains_newsletter: List[str]
    github_actionable_keywords: List[str]
    github_informational_keywords: List[str]
    github_repos: List[Dict]
    threads_actionable: List[Dict]
    actions: Dict[str, Dict]


# =============================================================================
# RULES LOADER (DIP-0002 Pattern)
# =============================================================================

class RulesLoader:
    """
    Load and merge rules from layered YAML files.

    Merge order: base → space → local (later overrides/extends earlier)
    """

    def __init__(self, module_path: Path, space_path: Optional[Path] = None):
        """
        Initialize rules loader.

        Args:
            module_path: Path to the mail module (.datacore/modules/mail/)
            space_path: Path to the space directory (e.g., 1-teamspace/)
        """
        self.module_path = module_path
        self.space_path = space_path

    def load(self) -> MergedRules:
        """Load and merge all rule layers."""
        # Layer 1: Base rules (PUBLIC)
        base_rules = self._load_yaml(self.module_path / "rules.base.yaml")

        # Layer 2: Space rules (SPACE)
        space_rules = {}
        if self.space_path:
            space_rules = self._load_yaml(self.space_path / ".datacore" / "mail-rules.yaml")

        # Layer 3: Local rules (PRIVATE)
        local_rules = self._load_yaml(self.module_path / "rules.local.yaml")

        # Merge layers
        return self._merge_rules(base_rules, space_rules, local_rules)

    def _load_yaml(self, path: Path) -> Dict:
        """Load YAML file, return empty dict if not exists."""
        if not path.exists():
            return {}
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")
            return {}

    def _merge_rules(self, base: Dict, space: Dict, local: Dict) -> MergedRules:
        """Merge rules from all layers."""
        # Helper to merge lists (extend, later wins for same pattern)
        def merge_list(key1: str, key2: str) -> List[Dict]:
            result = []
            patterns_seen = set()

            # Process in reverse order (local → space → base) so later wins
            for rules in [local, space, base]:
                items = rules.get(key1, {}).get(key2, []) or []
                for item in items:
                    if isinstance(item, dict):
                        pattern = item.get('pattern', '')
                        if pattern and pattern not in patterns_seen:
                            result.append(item)
                            patterns_seen.add(pattern)
                    elif isinstance(item, str):
                        if item not in patterns_seen:
                            result.append({'pattern': item})
                            patterns_seen.add(item)

            return result

        def merge_simple_list(key1: str, key2: str) -> List[str]:
            result = set()
            for rules in [base, space, local]:
                items = rules.get(key1, {}).get(key2, []) or []
                result.update(items)
            return list(result)

        def merge_actions() -> Dict[str, Dict]:
            result = {}
            for rules in [base, space, local]:
                actions = rules.get('actions', {}) or {}
                result.update(actions)
            return result

        return MergedRules(
            senders_actionable=merge_list('senders', 'actionable'),
            senders_research=merge_list('senders', 'research'),
            senders_newsletter=merge_list('senders', 'newsletter'),
            senders_api_cost_providers=merge_list('senders', 'api_cost_providers'),
            senders_ignore=merge_list('senders', 'ignore'),
            subjects_calendar=merge_list('subjects', 'calendar'),
            subjects_finance=merge_list('subjects', 'finance'),
            body_newsletter=merge_list('body', 'newsletter'),
            domains_newsletter=merge_simple_list('domains', 'newsletter'),
            github_actionable_keywords=merge_simple_list('github', 'actionable_keywords'),
            github_informational_keywords=merge_simple_list('github', 'informational_keywords'),
            github_repos=merge_list('github', 'repos'),
            threads_actionable=merge_list('threads', 'actionable'),
            actions=merge_actions()
        )


# =============================================================================
# CLASSIFIER
# =============================================================================

class ClassifierProcessor:
    """
    Two-dimensional email classifier using layered rules.

    Dimension 1 - Action Level: ACTIONABLE, INFORMATIONAL, CC, SPAM
    Dimension 2 - Track/Category: BUSINESS, RESEARCH, NEWSLETTER, GITHUB, FINANCE, CALENDAR
    """

    def __init__(self, config: Dict[str, Any], space_path: Optional[Path] = None):
        """
        Initialize classifier.

        Args:
            config: Processor configuration from mail.yaml
            space_path: Path to the space directory
        """
        self.config = config
        self.destination = config.get("destination", "org/inbox.org")
        self.my_email = config.get("address", "").lower()
        self.space_path = space_path

        # Load rules
        module_path = Path(__file__).parent.parent
        loader = RulesLoader(module_path, space_path)
        self.rules = loader.load()

    def _days_old(self, email_date: datetime) -> int:
        """Calculate how many days old an email is."""
        now = datetime.now(timezone.utc)
        if email_date.tzinfo is None:
            email_date = email_date.replace(tzinfo=timezone.utc)
        return (now - email_date).days

    def _get_cc_list(self, email: Email) -> List[str]:
        """Extract CC list from email headers."""
        for header in email.raw.get('payload', {}).get('headers', []):
            if header['name'].lower() == 'cc':
                return [c.strip().lower() for c in header['value'].split(',')]
        return []

    def _match_sender_rules(self, from_text: str, rules: List[Dict]) -> Optional[Dict]:
        """Check if sender matches any rules in list."""
        from_lower = from_text.lower()
        for rule in rules:
            pattern = rule.get('pattern', '').lower()
            if pattern and pattern in from_lower:
                return rule
        return None

    def _match_pattern_rules(self, text: str, rules: List[Dict]) -> Optional[Dict]:
        """Check if text matches any pattern rules."""
        text_lower = text.lower()
        for rule in rules:
            pattern = rule.get('pattern', '').lower()
            if pattern and pattern in text_lower:
                return rule
        return None

    def _is_github_notification(self, email: Email) -> bool:
        """Check if email is a GitHub notification that should be routed to GitHub processor."""
        sender_lower = email.sender.lower()
        # GitHub notification emails come from noreply6@service.example.com
        if 'noreply6@service.example.com' in sender_lower:
            return True
        return False

    def _extract_event_date(self, email: Email) -> Optional[datetime]:
        """Extract event date from email subject/body for calendar emails."""
        import re
        text = f"{email.subject} {email.body_text[:500] if email.body_text else ''}"

        # Pattern: Dec 18, 2025 or December 18, 2025 or Dec 18 2025
        match = re.search(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}', text, re.I)
        if match:
            for fmt in ['%b %d, %Y', '%B %d, %Y', '%b %d %Y', '%B %d %Y']:
                try:
                    return datetime.strptime(match.group().replace(',', ''), fmt.replace(',', ''))
                except ValueError:
                    pass

        # Pattern: 2025-12-18 (ISO format)
        match = re.search(r'\d{4}-\d{2}-\d{2}', text)
        if match:
            try:
                return datetime.strptime(match.group(), '%Y-%m-%d')
            except ValueError:
                pass

        # Pattern: 18/12/2025 or 12/18/2025 (common date formats)
        match = re.search(r'\d{1,2}/\d{1,2}/\d{4}', text)
        if match:
            for fmt in ['%d/%m/%Y', '%m/%d/%Y']:
                try:
                    return datetime.strptime(match.group(), fmt)
                except ValueError:
                    pass

        return None

    def _is_event_passed(self, event_date: Optional[datetime]) -> bool:
        """Check if event date has already passed."""
        if not event_date:
            return False
        return event_date.date() < datetime.now().date()

    def classify(self, email: Email) -> Classification:
        """
        Classify email using rules-based two-dimensional model.

        Args:
            email: Email to classify

        Returns:
            Classification result with action level and tracks
        """
        # === GITHUB ROUTING (check first) ===
        # Route GitHub notifications to specialized processor
        if self._is_github_notification(email):
            age = self._days_old(email.date)
            return Classification(
                action='GITHUB',
                tracks=['GITHUB'],
                confidence=0.95,
                actions=[],
                priority='MEDIUM',
                effort='Quick',
                suggested_title=email.subject,
                deadline=None,
                reasoning="GitHub notification - routing to GitHub processor",
                age_days=age,
                is_stale=age > 30,
                matched_rules=['github:notification:route'],
                processor='github'
            )

        sender_lower = email.sender.lower()
        sender_name_lower = (email.sender_name or '').lower()
        from_combined = f'{sender_name_lower} <{sender_lower}>'
        subject_lower = email.subject.lower()
        body_lower = email.body_text.lower()[:1000]
        all_text = from_combined + ' ' + subject_lower + ' ' + body_lower

        to_list = [r.lower() for r in email.recipients]
        cc_list = self._get_cc_list(email)

        is_to = any(self.my_email in r for r in to_list)
        is_cc = any(self.my_email in c for c in cc_list) and not is_to

        age = self._days_old(email.date)
        matched_rules = []

        # === DETERMINE TRACKS ===
        tracks: Set[str] = set()
        priority = 'MEDIUM'
        suggested_action = None
        newsletter_action = None
        newsletter_rule = None
        processor = None  # Default: no specialized processor

        # Check sender domain
        sender_domain = sender_lower.split('@')[-1] if '@' in sender_lower else ''

        # Finance (subject rules)
        finance_match = self._match_pattern_rules(subject_lower, self.rules.subjects_finance)
        if finance_match:
            tracks.add('FINANCE')
            matched_rules.append(f"finance:subject:{finance_match.get('pattern')}")
            if finance_match.get('action'):
                suggested_action = finance_match.get('action')
        # Also check body for finance keywords
        if not finance_match:
            finance_match = self._match_pattern_rules(body_lower, self.rules.subjects_finance)
            if finance_match:
                tracks.add('FINANCE')
                matched_rules.append(f"finance:body:{finance_match.get('pattern')}")

        # Calendar (subject rules)
        calendar_match = self._match_pattern_rules(subject_lower, self.rules.subjects_calendar)
        event_date = None
        event_passed = False
        if calendar_match:
            tracks.add('CALENDAR')
            matched_rules.append(f"calendar:{calendar_match.get('pattern')}")
            # Check if event has already passed
            event_date = self._extract_event_date(email)
            if event_date:
                event_passed = self._is_event_passed(event_date)
                if event_passed:
                    matched_rules.append(f"calendar:event_passed:{event_date.strftime('%Y-%m-%d')}")

        # GitHub detection
        is_github = 'noreply6@service.example.com' in sender_lower or 'noreply3@service.example.com' in sender_lower
        is_github = is_github or any(k in all_text for k in ['/pull/', '/issues/'])
        github_action = any(kw.lower() in all_text for kw in self.rules.github_actionable_keywords)
        if is_github:
            tracks.add('GITHUB')
            matched_rules.append("github:sender")

        # Research senders
        research_match = self._match_sender_rules(from_combined, self.rules.senders_research)
        if research_match:
            tracks.add('RESEARCH')
            matched_rules.append(f"research:{research_match.get('pattern')}")
            newsletter_action = research_match.get('action', 'prepare_for_research')
            newsletter_rule = research_match

        # AI/LLM API cost provider senders — mark FINANCE so a PDF-attached
        # invoice routes to the accounting processor via the existing
        # FINANCE + has_pdf check below (see :api-cost-providers: rules).
        api_cost_match = self._match_sender_rules(from_combined, self.rules.senders_api_cost_providers)
        if api_cost_match:
            tracks.add('FINANCE')
            matched_rules.append(f"api_cost_provider:{api_cost_match.get('pattern')}")

        # Newsletter detection
        is_newsletter = False
        newsletter_match = self._match_sender_rules(from_combined, self.rules.senders_newsletter)
        if newsletter_match:
            tracks.add('NEWSLETTER')
            is_newsletter = True
            matched_rules.append(f"newsletter:sender:{newsletter_match.get('pattern')}")
            if not newsletter_action:  # Research rule takes precedence
                newsletter_action = newsletter_match.get('action', 'archive_only')
                newsletter_rule = newsletter_match

        # Check newsletter domains
        if not is_newsletter and sender_domain in self.rules.domains_newsletter:
            tracks.add('NEWSLETTER')
            is_newsletter = True
            matched_rules.append(f"newsletter:domain:{sender_domain}")
            if not newsletter_action:
                newsletter_action = 'archive_only'

        # Check body for newsletter indicators
        if not is_newsletter and not is_github:
            body_match = self._match_pattern_rules(body_lower, self.rules.body_newsletter)
            if body_match:
                tracks.add('NEWSLETTER')
                is_newsletter = True
                matched_rules.append(f"newsletter:body:{body_match.get('pattern')}")
                if not newsletter_action:
                    newsletter_action = body_match.get('action', 'archive_only')
                    newsletter_rule = body_match

        # Spam/ignore senders
        ignore_match = self._match_sender_rules(from_combined, self.rules.senders_ignore)
        is_spam = ignore_match is not None
        if is_spam:
            tracks.add('SPAM')
            matched_rules.append(f"spam:{ignore_match.get('pattern')}")

        # Default to BUSINESS if no track
        if not tracks:
            tracks.add('BUSINESS')

        # === DETERMINE ACTION LEVEL ===
        if is_spam:
            action = 'SPAM'
        elif is_cc:
            action = 'CC'
        elif is_newsletter:
            action = 'INFORMATIONAL'
        elif research_match:
            action = 'INFORMATIONAL'  # Research is read for insights
        elif is_github:
            if github_action:
                action = 'ACTIONABLE'
                matched_rules.append("github:action_keyword")
            else:
                action = 'INFORMATIONAL'
        else:
            # Check actionable sender rules
            actionable_match = self._match_sender_rules(from_combined, self.rules.senders_actionable)
            if actionable_match:
                action = 'ACTIONABLE'
                priority = actionable_match.get('priority', 'MEDIUM')
                matched_rules.append(f"actionable:sender:{actionable_match.get('pattern')}")
            elif subject_lower.startswith('re:') or subject_lower.startswith('fwd:'):
                action = 'ACTIONABLE'
                matched_rules.append("actionable:reply_chain")
            elif 'CALENDAR' in tracks:
                action = 'ACTIONABLE'
                matched_rules.append("actionable:calendar")
            else:
                # Check thread rules
                thread_match = None
                for rule in self.rules.threads_actionable:
                    pattern = rule.get('subject_contains', '').lower()
                    if pattern and pattern in subject_lower:
                        thread_match = rule
                        break

                if thread_match:
                    action = 'ACTIONABLE'
                    priority = thread_match.get('priority', 'MEDIUM')
                    matched_rules.append(f"actionable:thread:{thread_match.get('subject_contains')}")
                else:
                    action = 'INFORMATIONAL'

        # Adjust priority for finance/calendar
        if action == 'ACTIONABLE':
            if 'CALENDAR' in tracks or 'FINANCE' in tracks:
                priority = 'HIGH'

        # Generate suggested title
        if action == 'ACTIONABLE':
            if 'reply' in body_lower or 'respond' in body_lower:
                suggested_title = f"Reply to {email.sender_name or email.sender} re: {email.subject}"
            elif 'review' in body_lower:
                suggested_title = f"Review: {email.subject}"
            elif 'CALENDAR' in tracks:
                suggested_title = f"Decide: {email.subject}"
            else:
                suggested_title = f"Follow up: {email.subject}"
        else:
            suggested_title = email.subject

        # Detect if should route to accounting processor
        if 'FINANCE' in tracks and email.has_attachments:
            # Check if has PDF attachment (likely invoice)
            has_pdf = any(
                att.get('filename', '').lower().endswith('.pdf')
                for att in email.attachments
            )
            if has_pdf:
                processor = 'accounting'
                matched_rules.append('finance:pdf_attachment:route_accounting')

        return Classification(
            action=action,
            tracks=list(tracks),
            confidence=0.85 if matched_rules else 0.60,
            actions=[suggested_title] if action == 'ACTIONABLE' else [],
            priority=priority,
            effort='Quick' if action != 'ACTIONABLE' else 'Moderate',
            suggested_title=suggested_title,
            deadline=None,
            reasoning=f"Action: {action}, Tracks: {', '.join(tracks)}, Rules: {len(matched_rules)}",
            age_days=age,
            is_stale=age > 30,
            matched_rules=matched_rules,
            processor=processor,
            newsletter_action=newsletter_action,
            newsletter_rule=newsletter_rule,
            event_passed=event_passed,
            event_date=event_date.strftime('%Y-%m-%d') if event_date else None
        )

    def batch_classify(self, emails: List[Email]) -> List[Dict[str, Any]]:
        """
        Classify a batch of emails.

        Args:
            emails: List of Email objects to classify

        Returns:
            List of dicts with classification results and email metadata
        """
        results = []
        for email in emails:
            c = self.classify(email)
            results.append({
                'action': c.action,
                'tracks': c.tracks,
                'confidence': c.confidence,
                'priority': c.priority,
                'effort': c.effort,
                'suggested_title': c.suggested_title,
                'deadline': c.deadline,
                'reasoning': c.reasoning,
                'age_days': c.age_days,
                'is_stale': c.is_stale,
                'matched_rules': c.matched_rules,
                'processor': c.processor,
                'newsletter_action': c.newsletter_action,
                'newsletter_rule': c.newsletter_rule,
                'event_passed': c.event_passed,
                'event_date': c.event_date,
                # Email metadata for downstream consumers
                'external_id': email.external_id,
                'email_id': email.id,
                'subject': email.subject,
                'sender': email.sender,
                'sender_name': email.sender_name,
                'date': email.date.isoformat() if email.date else '',
            })
        return results

    def process(self, email: Email, space_path: Path) -> Optional[str]:
        """
        Process email and create org entry if needed.

        Args:
            email: Email to process
            space_path: Path to the space directory

        Returns:
            Path to created org entry, or None if ignored
        """
        classification = self.classify(email)

        # Only create entries for actionable emails
        if classification.action not in ('ACTIONABLE',):
            return None

        # Create org entry
        org_file = space_path / self.destination
        entry = self._create_org_entry(email, classification)

        # Append to org file
        self._append_to_org_file(org_file, entry)

        return str(org_file)

    def _create_org_entry(self, email: Email, classification: Classification) -> str:
        """Create org-mode entry for email."""
        # Determine TODO state and priority
        state = "TODO"
        priority_char = classification.priority[0] if classification.priority else 'B'
        priority = f"[#{priority_char}] "

        # Build heading
        title = classification.suggested_title or email.subject
        heading = f"** {state} {priority}{title}"

        # Build tags from tracks
        tags = ':'.join(classification.tracks).lower()
        if tags:
            heading = f"{heading} :{tags}:"

        # Properties
        props = [
            ":PROPERTIES:",
            f":CREATED: [{datetime.now().strftime('%Y-%m-%d %a')}]",
            f":EXTERNAL_ID: {email.external_id}",
            f":EXTERNAL_URL: [[{email.gmail_url}][View in Gmail]]",
            f":SOURCE: email",
            f":SENDER: {email.sender}",
            f":RECEIVED: [{email.date.strftime('%Y-%m-%d %a %H:%M')}]",
            f":PRIORITY: {classification.priority}",
            f":EFFORT: {classification.effort}",
            f":TRACKS: {', '.join(classification.tracks)}",
            ":END:"
        ]

        if classification.is_stale:
            props.insert(-1, f":AGE_DAYS: {classification.age_days}")

        # Body
        body_parts = []

        if classification.actions:
            body_parts.append("**Actions:**")
            for action in classification.actions:
                body_parts.append(f"- {action}")
            body_parts.append("")

        # Original email info
        body_parts.append(f"From: {email.sender_name} <{email.sender}>")
        body_parts.append(f"Subject: {email.subject}")
        body_parts.append("")

        # Snippet
        if email.snippet:
            body_parts.append(email.snippet)

        # Attachments
        if email.has_attachments:
            body_parts.append("")
            body_parts.append("**Attachments:**")
            for att in email.attachments:
                size_kb = att.get('size', 0) / 1024
                body_parts.append(f"- {att['filename']} ({size_kb:.1f} KB)")

        # Stale warning
        if classification.is_stale:
            body_parts.append("")
            body_parts.append(f"⚠️ *This email is {classification.age_days} days old - review if still relevant*")

        # Matched rules (for debugging)
        if classification.matched_rules:
            body_parts.append("")
            body_parts.append(f"_Matched: {', '.join(classification.matched_rules)}_")

        # Combine
        lines = [heading] + props + [""] + body_parts + [""]
        return "\n".join(lines)

    def _append_to_org_file(self, org_file: Path, entry: str):
        """Append entry to org file."""
        # Ensure directory exists
        org_file.parent.mkdir(parents=True, exist_ok=True)

        # Create file with header if it doesn't exist
        if not org_file.exists():
            header = """#+TITLE: Inbox
#+FILETAGS: :inbox:
#+STARTUP: overview

* Inbox
"""
            org_file.write_text(header)

        # Append entry
        with open(org_file, 'a') as f:
            f.write(entry)


def batch_classify(
    emails: List[Email],
    config: Optional[Dict[str, Any]] = None,
    space_path: Optional[Path] = None,
    address: Optional[str] = None
) -> Dict[str, List[dict]]:
    """
    Classify a batch of emails and return grouped results.

    Convenience method that handles all processor setup with sensible defaults.

    Args:
        emails: List of emails to classify
        config: Optional processor configuration (auto-generated if not provided)
        space_path: Optional path to space for space-specific rules
        address: Optional email address (extracted from first email if not provided)

    Returns:
        Dict with action levels as keys and lists of classification results

    Example:
        # Simplest usage - just pass emails
        results = batch_classify(emails)

        # With custom address
        results = batch_classify(emails, address="user@example.com")

        # Full control
        results = batch_classify(
            emails,
            config={'destination': 'org/inbox.org', 'address': 'user@example.com'},
            space_path=Path('/path/to/space')
        )
    """
    # Auto-generate config if not provided
    if config is None:
        # Extract address from first email's recipients if available
        if address is None and emails:
            # Try to get from first email
            address = emails[0].recipients[0] if emails[0].recipients else ""

        config = {
            'destination': 'org/inbox.org',
            'address': address or ""
        }

    processor = ClassifierProcessor(config, space_path)
    results = {
        'ACTIONABLE': [],
        'INFORMATIONAL': [],
        'CC': [],
        'SPAM': [],
        'GITHUB': [],
        'ACCOUNTING': [],
        'ARCHIVE': []
    }

    for email in emails:
        classification = processor.classify(email)
        result = {
            'date': email.date.strftime('%Y-%m-%d'),
            'sender': email.sender_name or email.sender.split('@')[0],
            'email': email.sender,
            'subject': email.subject,
            'unread': email.is_unread,
            'action': classification.action,
            'tracks': classification.tracks,
            'has_attachment': email.has_attachments,
            'age_days': classification.age_days,
            'is_stale': classification.is_stale,
            'priority': classification.priority,
            'suggested_title': classification.suggested_title,
            'external_id': email.external_id,
            'gmail_url': email.gmail_url,
            'matched_rules': classification.matched_rules,
            'newsletter_action': classification.newsletter_action,
            'newsletter_rule': classification.newsletter_rule
        }
        results[classification.action].append(result)

    return results


def batch_process(
    emails: List[Email],
    space_path: Path,
    config: Optional[Dict[str, Any]] = None,
    address: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process a batch of emails - classify and create org entries for actionable ones.

    Convenience method that handles all processor setup and processes emails
    in a single call, creating org entries for actionable emails.

    Args:
        emails: List of emails to process
        space_path: Path to space directory (required for creating org entries)
        config: Optional processor configuration (auto-generated if not provided)
        address: Optional email address (extracted from first email if not provided)

    Returns:
        Dict with:
            - 'classifications': Full classification results by action level
            - 'created_entries': List of paths to created org entries
            - 'actionable_count': Number of actionable emails processed
            - 'total_count': Total number of emails processed

    Example:
        # Simplest usage
        result = batch_process(emails, space_path=Path('/path/to/space'))

        # With custom address
        result = batch_process(
            emails,
            space_path=Path('/path/to/space'),
            address="user@example.com"
        )

        # Full control
        result = batch_process(
            emails,
            space_path=Path('/path/to/space'),
            config={'destination': 'org/inbox.org', 'address': 'user@example.com'}
        )
    """
    # Auto-generate config if not provided
    if config is None:
        # Extract address from first email's recipients if available
        if address is None and emails:
            address = emails[0].recipients[0] if emails[0].recipients else ""

        config = {
            'destination': 'org/inbox.org',
            'address': address or ""
        }

    processor = ClassifierProcessor(config, space_path)
    created_entries = []

    # First classify all emails
    classifications = batch_classify(emails, config, space_path, address)

    # Process actionable emails to create org entries
    actionable_emails = classifications.get('ACTIONABLE', [])
    email_map = {e.external_id: e for e in emails}

    for classification_result in actionable_emails:
        external_id = classification_result.get('external_id', '')
        email = email_map.get(external_id)
        if email:
            entry_path = processor.process(email, space_path)
            if entry_path:
                created_entries.append(entry_path)

    return {
        'classifications': classifications,
        'created_entries': created_entries,
        'actionable_count': len(actionable_emails),
        'total_count': len(emails)
    }


def quick_classify(email: Email, address: str = "") -> Classification:
    """
    Classify a single email with minimal setup.

    Convenience wrapper for one-off classifications without maintaining
    a processor instance.

    Args:
        email: Email to classify
        address: Optional user email address for CC detection

    Returns:
        Classification result

    Example:
        classification = quick_classify(email, address="user@example.com")
        print(f"Action: {classification.action}")
        print(f"Tracks: {classification.tracks}")
    """
    processor = ClassifierProcessor(
        config={'destination': 'org/inbox.org', 'address': address},
        space_path=None
    )
    return processor.classify(email)
