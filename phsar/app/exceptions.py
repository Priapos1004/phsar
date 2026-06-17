from app.core.config import settings
from app.models.job import JobStatus


class PhsarBaseError(Exception):
    """Base class for all custom exceptions in the PHSAR project."""
    status_code: int = 400


class PermanentPhsarError(PhsarBaseError):
    """Marker for failures where retrying with the same input will produce
    the same result. The job worker uses isinstance(exc, PermanentPhsarError)
    to set retryable=False on the failed job, so the bell hides its retry
    button instead of letting the user spam jobs that can't ever succeed.

    Errors NOT in this branch (raw httpx errors, asyncio.TimeoutError,
    tenacity-exhausted retries, etc.) default to retryable=True since they
    plausibly recover when MAL or the network does.
    """


class MalIdAlreadyExistsError(PermanentPhsarError):
    """Raised when a media/anime with the same mal_id already exists in the database."""
    status_code = 409

    def __init__(self, mal_id: int, title: str):
        self.mal_id = mal_id
        self.title = title
        message = f"Media/Anime with mal_id {mal_id} already exists ('{title}')."
        super().__init__(message)


class AnimeNotFoundError(PermanentPhsarError):
    """Raised when a fuzzy `q=<title>` MAL search returns zero matches
    that aren't already in the catalog or filtered as unwanted. The
    title may well exist on MAL — the message is intentionally hedged
    ("no new match") rather than absolute ("not found") so the admin
    doesn't go chasing a MAL outage when in fact every hit was simply
    de-duped against existing rows."""
    status_code = 404

    def __init__(self, title: str):
        self.title = title
        message = f"No new anime matched '{title}' on MAL."
        super().__init__(message)


class TransientUpstreamError(PhsarBaseError):
    """Raised when MAL returns a successful HTTP response but with empty
    or malformed data — distinct from a real 404 (which would surface as
    HTTPStatusError from `_get`). Not a PermanentPhsarError, so the job
    worker stamps retryable=True and the bell shows its retry button;
    job_worker's classify_error also tags it as `upstream_outage` so
    the bell renders the friendly 'MAL temporarily unavailable' copy
    instead of leaking this internal message to users."""
    status_code = 502

    def __init__(self, identifier: str):
        self.identifier = identifier
        message = (
            f"MAL returned no data for {identifier}. "
            "This usually clears on retry."
        )
        super().__init__(message)


class AnimeFilteredOutError(PermanentPhsarError):
    """Raised when a seeded BFS run finds the target anime but our content
    filter (Music/PV/CM/Hentai/Unknown) rejects it. Distinct from
    AnimeNotFoundError so admin/cron logs reflect why the catalog
    doesn't have it — without this, every filtered seasonal entry
    looks like a missing MAL record in the jobs table."""
    status_code = 422

    def __init__(self, title: str, reason: str):
        self.title = title
        self.reason = reason
        message = f"'{title}' was filtered out as {reason} and not added to the catalog."
        super().__init__(message)


class MainMediaNotFoundError(PermanentPhsarError):
    """Raised when a relation graph has no media flagged as the main story.

    The full title/relation list is preserved on the instance for server-side
    logging; the user-facing message stays short so the bell isn't dominated
    by a Python list repr.
    """
    status_code = 404

    def __init__(self, title_relation_tuple: list[tuple[str, str]]):
        self.title_relation_tuple = title_relation_tuple
        first_title = title_relation_tuple[0][0] if title_relation_tuple else "(unknown)"
        message = (
            f"Couldn't identify a main story for '{first_title}'. "
            "Try a more specific search term."
        )
        super().__init__(message)


class NonNumericFieldError(PhsarBaseError):
    """Raised when a non-numeric field is passed to a numeric stats function."""

    def __init__(self, field_name: str):
        self.field_name = field_name
        message = f"The field '{field_name}' is not a numeric type."
        super().__init__(message)

class FieldExceedsMaximumNumberOfItemsError(PhsarBaseError):
    """Raised when a field in the search filter exceeds the maximum number of items allowed."""

    def __init__(self, field_name: str, item_count: int):
        self.item_count = item_count
        self.field_name = field_name
        message = f"'{field_name}' exceeds maximum allowed items ({item_count} > {settings.MAX_ITEMS}) to keep token size manageable."
        super().__init__(message)

class TokenTooLongError(PhsarBaseError):
    """Raised when the generated search token exceeds the maximum length."""

    def __init__(self, token_length: int):
        self.token_length = token_length
        message = f"Generated token is too long (size {token_length} > {settings.MAX_TOKEN_LENGTH}). Please reduce the number of filters."
        super().__init__(message)

class DecompressionError(PhsarBaseError):
    """Raised when decompression of a search token fails."""

    def __init__(self):
        message = "Failed to decompress search token"
        super().__init__(message)

class TokenVersionMismatchError(PhsarBaseError):
    """Raised when the token version does not match the current search API version."""

    def __init__(self, token_version: str):
        self.token_version = token_version
        message = f"Token version '{token_version}' does not match current search API version '{settings.CURRENT_SEARCH_API_VERSION}'."
        super().__init__(message)

class MalformedTokenError(PhsarBaseError):
    """Raised when the search token is malformed."""

    def __init__(self):
        message = "Invalid or malformed search token"
        super().__init__(message)

class UserAlreadyExistsError(PhsarBaseError):
    """Raised when a user tries to register with a username that already exists."""
    status_code = 409

    def __init__(self, username: str):
        self.username = username
        message = f"Username '{username}' already registered."
        super().__init__(message)


class InvalidRegistrationTokenError(PhsarBaseError):
    """Raised when a registration token is not found."""

    def __init__(self):
        message = "Invalid registration token."
        super().__init__(message)


class RegistrationTokenAlreadyUsedError(PhsarBaseError):
    """Raised when a registration token has already been used."""

    def __init__(self):
        message = "This registration token has already been used."
        super().__init__(message)


class RegistrationTokenExpiredError(PhsarBaseError):
    """Raised when a registration token has expired."""

    def __init__(self):
        message = "This registration token has expired."
        super().__init__(message)


class FieldDoesNotExistError(PhsarBaseError):
    """Raised when a requested field does not exist on a model."""

    def __init__(self, field_name: str, model_name: str):
        self.field_name = field_name
        self.model_name = model_name
        message = f"Field '{field_name}' does not exist in model {model_name}"
        super().__init__(message)


class CouldNotValidateCredentialsError(PhsarBaseError):
    """Raised when credentials cannot be validated."""
    status_code = 401

    def __init__(self):
        message = "Could not validate credentials"
        super().__init__(message)

class InsufficientPermissionsError(PhsarBaseError):
    """Raised when a user does not have sufficient permissions to access a resource."""
    status_code = 403

    def __init__(self):
        message = "Insufficient permissions"
        super().__init__(message)

class MissingSearchDataError(PhsarBaseError):
    """Raised when the search data is missing in the token."""

    def __init__(self):
        message = "Missing search data in token"
        super().__init__(message)


class InvalidSearchTypeError(PhsarBaseError):
    """Raised when a search type is not supported for the given endpoint."""

    def __init__(self, search_type: str):
        message = f"Search type '{search_type}' is not supported on this endpoint."
        super().__init__(message)


class RatingNotFoundError(PhsarBaseError):
    """Raised when a rating is not found or not owned by the user."""
    status_code = 404

    def __init__(self, identifier: str):
        message = f"Rating not found: '{identifier}'."
        super().__init__(message)


class MediaNotFoundError(PhsarBaseError):
    """Raised when a media UUID does not resolve to an existing media."""
    status_code = 404

    def __init__(self, media_identifier: str):
        message = f"Media not found: '{media_identifier}'."
        super().__init__(message)


class AnimeNotFoundByUuidError(PhsarBaseError):
    """Raised when an anime UUID does not resolve to an existing anime."""
    status_code = 404

    def __init__(self, uuid: str):
        message = f"Anime not found: '{uuid}'."
        super().__init__(message)


class UserSettingsNotFoundError(PhsarBaseError):
    """Raised when user settings are not found (should not happen if seeding is correct)."""
    status_code = 404

    def __init__(self):
        message = "User settings not found."
        super().__init__(message)


class RegistrationTokenNotFoundError(PhsarBaseError):
    """Raised when a registration token UUID does not resolve to an existing token."""
    status_code = 404

    def __init__(self, uuid: str):
        message = f"Registration token not found: '{uuid}'."
        super().__init__(message)


class CannotDeleteUsedTokenError(PhsarBaseError):
    """Raised when attempting to delete a registration token that has been used."""
    status_code = 400

    def __init__(self):
        message = "Cannot delete a registration token that has already been used."
        super().__init__(message)


class InvalidPasswordError(PhsarBaseError):
    """Raised when the provided password does not match the user's current password."""
    status_code = 403

    def __init__(self):
        message = "Invalid password."
        super().__init__(message)


class BackupNotFoundError(PhsarBaseError):
    """Raised when a backup filename does not resolve to a file on disk."""
    status_code = 404

    def __init__(self, filename: str):
        message = f"Backup not found: '{filename}'."
        super().__init__(message)


class BackupIntegrityError(PhsarBaseError):
    """Raised when a freshly created or uploaded backup fails pg_restore --list."""
    status_code = 500

    def __init__(self, filename: str, detail: str):
        message = f"Backup '{filename}' failed integrity check: {detail}"
        super().__init__(message)


class BackupDiskSpaceError(PhsarBaseError):
    """Raised when the backup volume has insufficient free space for a new dump."""
    status_code = 507

    def __init__(self, free_bytes: int, required_bytes: int):
        free_mb = free_bytes / (1024 * 1024)
        required_mb = required_bytes / (1024 * 1024)
        message = (
            f"Insufficient disk space on backup volume: "
            f"{free_mb:.0f} MB free, need at least {required_mb:.0f} MB."
        )
        super().__init__(message)


class BackupRestoreError(PhsarBaseError):
    """Raised when pg_restore exits non-zero during a restore."""
    status_code = 500

    def __init__(self, filename: str, detail: str):
        message = f"Restore from '{filename}' failed: {detail}"
        super().__init__(message)


class BackupConfirmationMismatchError(PhsarBaseError):
    """Raised when the restore confirmation string does not match the caller's username."""
    status_code = 400

    def __init__(self):
        message = "Restore confirmation did not match your username."
        super().__init__(message)


class InvalidCronTokenError(PhsarBaseError):
    """Raised when a cron-authenticated endpoint gets a bad/missing bearer token."""
    status_code = 401

    def __init__(self):
        message = "Invalid or missing cron token."
        super().__init__(message)


class DuplicateBackupError(PhsarBaseError):
    """Raised when an uploaded backup has the same content hash as an existing dump."""
    status_code = 409

    def __init__(self, existing_metadata):
        # Carry the full matched BackupMetadata (duck-typed to avoid an
        # exceptions.py → schemas import) so the backup dispatcher can
        # convert this into a 'deduped_against' success outcome without
        # re-scanning the backup dir (which would shell out to
        # pg_restore --list for any dump missing a sidecar).
        self.existing_metadata = existing_metadata
        message = f"This dump is identical to an existing backup: '{existing_metadata.filename}'."
        super().__init__(message)


class JobQueueLimitExceededError(PhsarBaseError):
    """Raised when a user tries to enqueue a job past the per-user submission cap."""
    status_code = 409

    def __init__(self, limit: int):
        self.limit = limit
        message = f"You already have {limit} active scrape jobs. Wait for one to finish before queueing more."
        super().__init__(message)


class DailyJobLimitExceededError(PermanentPhsarError):
    """Raised when a user exhausts the rolling 24h user_scrape quota.

    Marked permanent so the bell hides the retry button — retrying today
    still hits the same wall. The user must wait for the window to roll
    forward (the oldest in-window job's created_at + 24h)."""
    status_code = 429

    def __init__(self, limit: int):
        self.limit = limit
        message = (
            f"You've hit your daily limit of {limit} anime additions. "
            "Please try again tomorrow."
        )
        super().__init__(message)


class JobNotFoundError(PhsarBaseError):
    """Raised when a job UUID doesn't resolve, or the requester isn't allowed to see it."""
    status_code = 404

    def __init__(self, uuid: str):
        message = f"Job not found: '{uuid}'."
        super().__init__(message)


class DuplicateScrapeQueryError(PhsarBaseError):
    """Raised when a user_scrape with the same query was run recently —
    redundant because the BFS would just produce empty results."""
    status_code = 409

    def __init__(self, query: str, previous_status: JobStatus, hours_ago: int):
        self.query = query
        self.previous_status = previous_status
        self.hours_ago = hours_ago
        if previous_status in (JobStatus.queued, JobStatus.running):
            message = f"'{query}' is already being scraped — check the bell for progress."
        else:
            ago = "less than an hour" if hours_ago < 1 else f"{hours_ago}h"
            message = (
                f"'{query}' was already scraped {ago} ago. "
                "New seasonal releases land via the nightly update — "
                "try again in a few days if something looks missing."
            )
        super().__init__(message)


class MergeCandidateNotFoundError(PhsarBaseError):
    """Raised when a merge candidate UUID doesn't resolve."""
    status_code = 404

    def __init__(self, uuid: str):
        message = f"Merge candidate not found: '{uuid}'."
        super().__init__(message)


class MergeCandidateAlreadyResolvedError(PhsarBaseError):
    """Raised when admin tries to merge or dismiss a candidate that's
    already in a terminal state."""
    status_code = 409

    def __init__(self, status: str):
        message = f"Merge candidate is already {status} — cannot resolve again."
        super().__init__(message)


class MergeMalIdConflictError(PhsarBaseError):
    """Raised when two anime up for merge share a media mal_id.

    Per design, this should never happen — Media.mal_id is globally unique.
    Surface 409 so an admin investigates the underlying duplicate before
    merging."""
    status_code = 409

    def __init__(self, mal_id: int):
        self.mal_id = mal_id
        message = (
            f"Both anime have a media with mal_id {mal_id}. "
            "This should never happen — investigate the duplicate before merging."
        )
        super().__init__(message)


class InvalidMergeKeepError(PhsarBaseError):
    """Raised when the admin's keep_uuid for a merge doesn't match either
    of the candidate's two anime. Almost always a stale frontend payload."""
    status_code = 400

    def __init__(self, keep_uuid: str):
        message = (
            f"keep_uuid '{keep_uuid}' does not match either anime in this "
            "merge candidate."
        )
        super().__init__(message)


class SplitCandidateNotFoundError(PhsarBaseError):
    """Raised when a split candidate UUID doesn't resolve."""
    status_code = 404

    def __init__(self, uuid: str):
        message = f"Split candidate not found: '{uuid}'."
        super().__init__(message)


class SplitCandidateAlreadyResolvedError(PhsarBaseError):
    """Raised when admin tries to split or dismiss a candidate that's
    already in a terminal state."""
    status_code = 409

    def __init__(self, status: str):
        message = f"Split candidate is already {status} — cannot resolve again."
        super().__init__(message)


class SplitCandidateStaleError(PhsarBaseError):
    """Raised when the cluster payload no longer matches what the
    classifier would produce on the source anime's current graph (e.g.,
    sweep added new media that shifted the structure between detection
    and execution, or members got demoted below the substance gate
    leaving the cluster too small to split). Admin re-runs detection
    to refresh."""
    status_code = 409

    def __init__(self, reason: str):
        super().__init__(f"Split candidate is stale: {reason}. Re-run detection.")


class BackupUploadTooLargeError(PhsarBaseError):
    status_code = 413

    def __init__(self, observed_bytes: int, max_bytes: int):
        observed_mb = observed_bytes / (1024 * 1024)
        max_mb = max_bytes / (1024 * 1024)
        message = (
            f"Uploaded backup is too large: {observed_mb:.0f} MB "
            f"(limit: {max_mb:.0f} MB)."
        )
        super().__init__(message)
