"""Lock and verify MCP tool surfaces; the practical outcome of the schema-drift study."""

from .surface import Finding, Report, check, diff, lockfile, normalize, total_loss

__all__ = ["Finding", "Report", "check", "diff", "lockfile", "normalize", "total_loss"]
