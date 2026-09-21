"""
GitHub notification processor for team emails.

Specialized processing for GitHub notifications:
- Fetches current PR/Issue state via gh CLI
- Finds linked org tasks by :EXTERNAL_ID:
- Auto-updates tasks when issues/PRs close
- Surfaces only emails needing human reply
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class GitHubContext:
    """Context fetched from GitHub."""
    repo: str                    # owner/repo
    number: int                  # issue/PR number
    type: str                    # 'issue' or 'pr'
    state: str                   # open/closed/merged
    title: str
    author: str
    comments_count: int
    last_commenter: Optional[str] = None
    my_involvement: str = 'watching'  # 'author', 'reviewer', 'mentioned', 'watching'
    labels: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LinkedTask:
    """Org task linked to this GitHub item."""
    file_path: Path
    line_number: int
    headline: str
    state: str                   # TODO, DONE, etc.
    external_id: str
    priority: Optional[str] = None


@dataclass
class GitHubProcessorResult:
    """Result of GitHub processing."""
    action: str                  # REPLY_NEEDED, UPDATE_TASK, ARCHIVE_ONLY, ESCALATE
    github_context: Optional[GitHubContext]
    linked_task: Optional[LinkedTask]
    suggested_reply: Optional[str] = None
    task_update: Optional[str] = None   # 'mark_done', 'add_note', None
    summary: str = ""
    event_type: str = "unknown"


class GitHubProcessor:
    """Process GitHub notification emails with context awareness."""

    # GitHub username for detecting involvement
    MY_GITHUB_USERNAME = "username"  # TODO: Make configurable

    def __init__(self, space_path: Path, org_files: List[str] = None):
        """
        Initialize GitHub processor.

        Args:
            space_path: Path to the space (e.g., ~/Data/0-personal)
            org_files: List of org files to search for linked tasks
        """
        self.space_path = space_path
        self.org_files = org_files or ['org/next_actions.org', 'org/inbox.org']

    def process(self, email) -> GitHubProcessorResult:
        """
        Process a GitHub notification email.

        Args:
            email: Email object from gmail adapter

        Returns:
            GitHubProcessorResult with action and context
        """
        # 1. Parse GitHub metadata from email subject/headers
        repo, number, event_type = self._parse_github_email(email)

        if not repo or not number:
            return GitHubProcessorResult(
                action='ARCHIVE_ONLY',
                github_context=None,
                linked_task=None,
                summary="Could not parse GitHub notification",
                event_type='unknown'
            )

        # 2. Fetch current state via gh CLI
        gh_context = self._fetch_github_context(repo, number)

        # 3. Find linked org task by :EXTERNAL_ID:
        linked_task = self._find_linked_task(repo, number)

        # 4. Determine action
        action = self._classify_action(email, gh_context, linked_task, event_type)

        # 5. Generate suggested reply if needed
        suggested_reply = None
        if action == 'REPLY_NEEDED' and gh_context:
            suggested_reply = self._draft_reply(gh_context, email)

        # 6. Determine task update
        task_update = None
        if linked_task and gh_context and gh_context.state in ('closed', 'merged'):
            task_update = 'mark_done'

        # 7. Generate summary
        summary = self._generate_summary(gh_context, linked_task, action, event_type)

        return GitHubProcessorResult(
            action=action,
            github_context=gh_context,
            linked_task=linked_task,
            suggested_reply=suggested_reply,
            task_update=task_update,
            summary=summary,
            event_type=event_type
        )

    def _parse_github_email(self, email) -> tuple:
        """
        Extract repo and number from email subject.

        Patterns:
        - [owner/repo] Title (#123)
        - [owner/repo] Title (Issue #123)
        - Re: [owner/repo] Title (#123)
        """
        subject = email.subject

        # Pattern: [owner/repo] ... (#123) or [owner/repo] ... (Issue #123)
        repo_match = re.search(r'\[([^/\]]+/[^\]]+)\]', subject)
        num_match = re.search(r'#(\d+)', subject)

        repo = repo_match.group(1) if repo_match else None
        number = int(num_match.group(1)) if num_match else None

        # Detect event type from subject
        event_type = self._detect_event_type(subject, email)

        return repo, number, event_type

    def _detect_event_type(self, subject: str, email) -> str:
        """Detect the type of GitHub event from subject and headers."""
        subject_lower = subject.lower()

        if 'merged' in subject_lower:
            return 'merged'
        elif 'closed' in subject_lower:
            return 'closed'
        elif 'opened' in subject_lower or 'created' in subject_lower:
            return 'opened'
        elif 'review requested' in subject_lower:
            return 'review_requested'
        elif 'approved' in subject_lower:
            return 'approved'
        elif 'changes requested' in subject_lower:
            return 'changes_requested'
        elif 'commented' in subject_lower or 'left a comment' in subject_lower:
            return 'comment'
        elif 'mentioned' in subject_lower:
            return 'mentioned'
        elif 'assigned' in subject_lower:
            return 'assigned'

        # Check X-GitHub-Reason header if available
        if hasattr(email, 'raw') and email.raw:
            headers = email.raw.get('payload', {}).get('headers', [])
            for header in headers:
                if header.get('name', '').lower() == 'x-github-reason':
                    reason = header.get('value', '').lower()
                    if 'review_requested' in reason:
                        return 'review_requested'
                    elif 'mention' in reason:
                        return 'mentioned'
                    elif 'author' in reason:
                        return 'author_activity'

        return 'comment'  # Default

    def _fetch_github_context(self, repo: str, number: int) -> Optional[GitHubContext]:
        """Fetch current GitHub state via gh CLI."""
        # Try as PR first
        pr_context = self._try_fetch_pr(repo, number)
        if pr_context:
            return pr_context

        # Try as issue
        issue_context = self._try_fetch_issue(repo, number)
        if issue_context:
            return issue_context

        return None

    def _try_fetch_pr(self, repo: str, number: int) -> Optional[GitHubContext]:
        """Try to fetch as PR."""
        try:
            result = subprocess.run(
                ['gh', 'pr', 'view', str(number), '--repo', repo, '--json',
                 'state,title,author,comments,reviews,labels,reviewRequests'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return GitHubContext(
                    repo=repo,
                    number=number,
                    type='pr',
                    state=data.get('state', 'unknown').lower(),
                    title=data.get('title', ''),
                    author=data.get('author', {}).get('login', ''),
                    comments_count=len(data.get('comments', [])),
                    last_commenter=self._get_last_commenter(data.get('comments', [])),
                    my_involvement=self._detect_pr_involvement(data),
                    labels=[l.get('name', '') for l in data.get('labels', [])],
                    raw=data
                )
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        return None

    def _try_fetch_issue(self, repo: str, number: int) -> Optional[GitHubContext]:
        """Try to fetch as issue."""
        try:
            result = subprocess.run(
                ['gh', 'issue', 'view', str(number), '--repo', repo, '--json',
                 'state,title,author,comments,labels,assignees'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return GitHubContext(
                    repo=repo,
                    number=number,
                    type='issue',
                    state=data.get('state', 'unknown').lower(),
                    title=data.get('title', ''),
                    author=data.get('author', {}).get('login', ''),
                    comments_count=len(data.get('comments', [])),
                    last_commenter=self._get_last_commenter(data.get('comments', [])),
                    my_involvement=self._detect_issue_involvement(data),
                    labels=[l.get('name', '') for l in data.get('labels', [])],
                    raw=data
                )
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        return None

    def _get_last_commenter(self, comments: List[Dict]) -> Optional[str]:
        """Get the username of the last commenter."""
        if not comments:
            return None
        last_comment = comments[-1]
        return last_comment.get('author', {}).get('login')

    def _detect_pr_involvement(self, data: Dict) -> str:
        """Detect my involvement level in a PR."""
        my_user = self.MY_GITHUB_USERNAME.lower()

        # Check if I'm the author
        author = data.get('author', {}).get('login', '').lower()
        if author == my_user:
            return 'author'

        # Check if review was requested from me
        review_requests = data.get('reviewRequests', [])
        for req in review_requests:
            if req.get('login', '').lower() == my_user:
                return 'reviewer'

        # Check if I've reviewed
        reviews = data.get('reviews', [])
        for review in reviews:
            if review.get('author', {}).get('login', '').lower() == my_user:
                return 'reviewer'

        # Check if mentioned in comments
        comments = data.get('comments', [])
        for comment in comments:
            body = comment.get('body', '').lower()
            if f'@{my_user}' in body:
                return 'mentioned'

        return 'watching'

    def _detect_issue_involvement(self, data: Dict) -> str:
        """Detect my involvement level in an issue."""
        my_user = self.MY_GITHUB_USERNAME.lower()

        # Check if I'm the author
        author = data.get('author', {}).get('login', '').lower()
        if author == my_user:
            return 'author'

        # Check if I'm assigned
        assignees = data.get('assignees', [])
        for assignee in assignees:
            if assignee.get('login', '').lower() == my_user:
                return 'assignee'

        # Check if mentioned in comments
        comments = data.get('comments', [])
        for comment in comments:
            body = comment.get('body', '').lower()
            if f'@{my_user}' in body:
                return 'mentioned'

        return 'watching'

    def _find_linked_task(self, repo: str, number: int) -> Optional[LinkedTask]:
        """Search org files for task with matching :EXTERNAL_ID: or GitHub URL."""
        patterns = [
            f'github:{repo}#{number}',
            f'github:{repo}/issues/{number}',
            f'github:{repo}/pull/{number}',
            f'github.com/{repo}/issues/{number}',
            f'github.com/{repo}/pull/{number}',
            f'{repo}#{number}',
        ]

        for org_file_rel in self.org_files:
            file_path = self.space_path / org_file_rel
            if not file_path.exists():
                # Also check parent (for 0-personal when space_path is ~/Data)
                file_path = self.space_path.parent / '0-personal' / org_file_rel
                if not file_path.exists():
                    continue

            try:
                content = file_path.read_text()
                lines = content.split('\n')

                for i, line in enumerate(lines):
                    for pattern in patterns:
                        if pattern in line:
                            # Found! Now find the headline
                            headline, state, priority = self._extract_task_info(lines, i)
                            return LinkedTask(
                                file_path=file_path,
                                line_number=i + 1,
                                headline=headline,
                                state=state,
                                external_id=pattern,
                                priority=priority
                            )
            except Exception:
                continue

        return None

    def _extract_task_info(self, lines: List[str], match_line_idx: int) -> tuple:
        """
        Extract task headline, state, and priority from org content.

        Searches backwards from match_line_idx to find the headline.
        """
        headline = ""
        state = "UNKNOWN"
        priority = None

        # Search backwards for headline
        for i in range(match_line_idx, -1, -1):
            line = lines[i]
            # Check if it's a headline (starts with one or more *)
            if re.match(r'^\*+ ', line):
                headline = line.strip()
                # Extract state
                state_match = re.search(r'\*+ (TODO|DONE|NEXT|WAITING|CANCELLED)', line)
                if state_match:
                    state = state_match.group(1)
                # Extract priority
                priority_match = re.search(r'\[#([ABC])\]', line)
                if priority_match:
                    priority = priority_match.group(1)
                break

        return headline, state, priority

    def _classify_action(
        self,
        email,
        gh_context: Optional[GitHubContext],
        linked_task: Optional[LinkedTask],
        event_type: str
    ) -> str:
        """Determine what action to take."""
        if gh_context is None:
            return 'ARCHIVE_ONLY'  # Can't fetch context, just archive

        # If closed/merged and has linked task → update task
        if gh_context.state in ('closed', 'merged') and linked_task:
            if linked_task.state != 'DONE':
                return 'UPDATE_TASK'
            return 'ARCHIVE_ONLY'

        # Review requested from me
        if event_type == 'review_requested' and gh_context.my_involvement == 'reviewer':
            return 'REPLY_NEEDED'

        # I'm mentioned
        if event_type == 'mentioned' or gh_context.my_involvement == 'mentioned':
            return 'REPLY_NEEDED'

        # Changes requested on my PR
        if event_type == 'changes_requested' and gh_context.my_involvement == 'author':
            return 'REPLY_NEEDED'

        # Comment on my PR/issue and I'm the author
        if event_type == 'comment' and gh_context.my_involvement == 'author':
            return 'REPLY_NEEDED'

        # Just watching or informational
        return 'ARCHIVE_ONLY'

    def _draft_reply(self, gh_context: GitHubContext, email) -> Optional[str]:
        """Draft a suggested reply based on context."""
        # This is a placeholder - could use AI to generate contextual replies
        if gh_context.type == 'pr':
            if gh_context.my_involvement == 'reviewer':
                return "TODO: Review this PR"
            elif gh_context.my_involvement == 'author':
                return "TODO: Address feedback on PR"
        elif gh_context.type == 'issue':
            if gh_context.my_involvement == 'author':
                return "TODO: Respond to comment"
            elif gh_context.my_involvement == 'mentioned':
                return "TODO: Respond to mention"
        return None

    def _generate_summary(
        self,
        gh_context: Optional[GitHubContext],
        linked_task: Optional[LinkedTask],
        action: str,
        event_type: str
    ) -> str:
        """Generate a human-readable summary."""
        if not gh_context:
            return "GitHub notification (could not fetch details)"

        type_icon = "🔀" if gh_context.type == 'pr' else "📋"
        state_icon = {
            'open': '🟢',
            'closed': '🔴',
            'merged': '🟣',
        }.get(gh_context.state, '⚪')

        summary = f"{type_icon} {gh_context.repo}#{gh_context.number}: {gh_context.title[:50]}"

        if gh_context.state in ('closed', 'merged'):
            summary += f" [{state_icon} {gh_context.state}]"

        if linked_task:
            summary += f" → linked to org task ({linked_task.state})"

        if action == 'REPLY_NEEDED':
            summary += " ⚠️ ACTION NEEDED"
        elif action == 'UPDATE_TASK':
            summary += " 📝 will update task"

        return summary


def update_org_task(task: LinkedTask, new_state: str) -> bool:
    """
    Update org task state (e.g., TODO → DONE).

    Args:
        task: LinkedTask to update
        new_state: New state (e.g., 'DONE')

    Returns:
        True if updated successfully
    """
    try:
        content = task.file_path.read_text()
        lines = content.split('\n')

        # Find the headline line
        for i, line in enumerate(lines):
            # Check if this line contains the task (by headline or external_id)
            if task.headline and task.headline in line:
                # Update state in headline
                old_states = ['TODO', 'NEXT', 'WAITING']
                for old_state in old_states:
                    if f'* {old_state}' in line or f'** {old_state}' in line or f'*** {old_state}' in line:
                        lines[i] = line.replace(f' {old_state} ', f' {new_state} ')

                        # Add CLOSED timestamp after headline
                        if new_state == 'DONE':
                            closed_line = f"CLOSED: [{datetime.now().strftime('%Y-%m-%d %a')}]"
                            # Insert after headline, before properties
                            lines.insert(i + 1, closed_line)

                        task.file_path.write_text('\n'.join(lines))
                        return True
                break

        return False
    except Exception:
        return False
