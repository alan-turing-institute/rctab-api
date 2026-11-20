
# Logging

## Logging module

Import the `logging` module in the Python scripts or modules where you want to log information.

```python
import logging
```

## Log levels

The default logging threshold is `WARNING`. To change this, set a `LOG_LEVEL` environment variable to the desired log level.

```bash
export LOG_LEVEL=INFO
```

When logging a message, choose the level that corresponds to the severity of the message. The following guideline might be useful:

- `INFO`: General information about the application’s progress.
- `WARNING`: Indication of potential issues or unexpected behavior that may need attention.
- `DEBUG`: Detailed information, typically useful only for debugging purposes.
- `ERROR`: Record of error events that might still allow the application to continue running.
- `CRITICAL`: Severe error event that may cause the application to terminate.

## Log messages

Log messages should be descriptive and provide context that help to understand the log entry.

Use a `Logger` to log message. First, create an instance of a `Logger` object to log messages:

```python
# Logger for current module
logger = logging.getLogger(__name__)

# Log messages with different severity
logger.info("This is just a message with some information.")
logger.warning("Something unexpected occured.")
logger.error("An error occured.")
logger.exception("This logs an error message along with the traceback.")
```

This creates a `Logger` on module level, where `__name__` is the module’s name in the Python package namespace.
To log a message, choose the function that reflects the appropriate severity. When exceptions occur,`logger.exception()` can be very useful for debugging, since it logs the error message along the traceback.

## Azure Application Insights

The RCTab API sends its logs to [Azure Application Insights](https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview), which can, amongst other things, collect and store trace logging data.
Every Application Insights resource deployed by [rctab-infrastructure](https://github.com/alan-turing-institute/rctab-infrastructure) writes to the same Log Analytics workspace, so the logs of the RCTab API and the Azure function apps can be queried in one place.

### Configuration

Logs are only sent if a connection string is provided.

- On Azure, the `APPLICATIONINSIGHTS_CONNECTION_STRING` application setting is set for you when the infrastructure is deployed.
- When running the RCTab API locally, add the connection string of an Application Insights resource to the `.env` file:
  `APPLICATIONINSIGHTS_CONNECTION_STRING="my-connection-string"`
  To find the connection string, navigate to the Application Insights resource on the Azure portal.

The `OTEL_SERVICE_NAME` environment variable sets the `AppRoleName` of each record.
It defaults to `rctab-api`.

### Custom logging functionality

The custom functionality to send logs to Application Insights can be found in `rctab/logutils.py`.
It uses the [Azure Monitor OpenTelemetry Distro](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-enable?tabs=python).
Only logs are exported: tracing, metrics and automatic instrumentation of libraries are disabled.

The function `set_log_handler()` in `rctab/logutils.py`

- Configures Azure Monitor, once per process, with a handler on the `rctab` logger.
  All logging from `rctab/` and further down in the Python module hierarchy is therefore sent to Application Insights.
- Adds a handler to the logger of the provided name, if it is not the `rctab` logger.
  The Celery worker uses this for the `celery` and `celery.task` loggers.

Each record carries the following custom dimensions:

- `logger_name`: the name of the logger that emitted the record, e.g. `rctab.routers.accounting.send_emails`.
- `code.file.path`, `code.function.name` and `code.line.number`: where in the code the record was emitted.

### View logs on Azure portal

To view the log messages,

- Go to the Application Insights resource, or the Log Analytics workspace, on the Azure portal.
- Navigate to `Logs`.
- The logs are in the `AppTraces` table.
  Records logged with `logger.exception()` are in the `AppExceptions` table.

An example query to explore the table contents could be

```text
AppTraces
| where AppRoleName == "rctab-api"
| extend logger_name = tostring(Properties.logger_name)
| extend function = tostring(Properties["code.function.name"])
| extend line_number = toint(Properties["code.line.number"])
```

Running the query will show you the logs (within the specified `Time range`) in a table layout including columns for the logger name, the function that logged the message and the corresponding line in the code.

You can further filter the log messages.
For example

```text
AppTraces
| extend logger_name = tostring(Properties.logger_name)
| where logger_name == "rctab.main"
| where Message has "Starting server"
```

The log levels used with the Python `Logger` correspond to `SeverityLevel` in `AppTraces`. `SeverityLevel` uses integer numbers. For convenience, these numbers can be easily substituted with the more familiar corresponding log levels by adding the following line to the `kusto` query:

```text
| extend log_level = case(SeverityLevel == 0, "DEBUG", SeverityLevel == 1, "INFO", SeverityLevel == 2, "WARNING", SeverityLevel == 3, "ERROR", SeverityLevel == 4, "CRITICAL", "UNKNOWN")
```
