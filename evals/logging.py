import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),  # pretty output for dev
    ],
)


def get_logger(module_name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance for structured logging."""
    log = structlog.get_logger()
    if module_name:
        log = log.bind(module=module_name)
    return log
