
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

## Centralised Logging

### Azure Application Insights

It can be useful to collect and view the Python logs produced by the RCTab API and the Azure function apps in one place.
To do so, the logs can be sent to [Azure Application Insights](https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview?tabs=net), which can, amongst other things, collect and store trace logging data.

You need to provide a connection string to an Azure Application Insights resource to which the logs can be sent.

- If you want to set up a new Azure Application Insights resource, follow these [instructions](https://learn.microsoft.com/en-us/azure/azure-monitor/app/create-new-resource?tabs=net#create-an-application-insights-resource-1).
- To find the connection string, navigate to the Azure Application Insights resource on the Azure portal.
- Add the connection string either
  - to the `.env` file, if you run the RCTab API locally:
  `CENTRAL_LOGGING_CONNECTION_STRING="my-connection-string"`
  - or to the Azure portal Application Settings, if you deployed the RCTab API to Azure:
    - On the left hand panel under `Settings` select `Configruation`
    - Under the tab `Application settings`, click `+ New application setting`
    - Provide the name `CENTRAL_LOGGING_CONNECTION_STRING` and as value the connection string to your Azure Application Insights resource.
    - Save the new setting.

### Custom logging functionality

Once you added a connection string to the `.env` file or to the Application Settings on the Azure portal, by default, all logging from `rctab/` and further down in the Python module hierarchy are sent to the Application Insights.
You can change this by providing a name for the logger in `set_log_handler(name="my-logger-name")` during `startup()` in `main.py`.

The custom functionality to centralise logging can be found in `rctab/logutils.py`.
It uses the [OpenCensus Python SDK](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opencensus-python) to send logs to the Application Insights.

The function `set_log_handler()` in `rctab/logutils.py`

- Gets a logger of provided name (default: `rctab`)
- Adds an `AzureLogHandler` to this logger if a connection string is provided.
- Adds a filter that appends custom dimensions in form of a key-value pair (e.g. `{"logger_name": "logger_rctab"`) to each log record.
  The custom dimensions are hard-coded in the function definition of `set_log_handler()` and can be changed there.

### View logs on Azure portal

To view the log messages,

- Go to the Application Insights resource on the Azure portal.
- Navigate to `Logs`.
- The logs are in the `traces` table under the `Tables` tab.

An example query to explore the table contents could be

```text
traces
| extend logger_name = tostring(customDimensions.logger_name)
| extend module = tostring(customDimensions.module)
| extend line_number = tostring(customDimensions.lineNumber)
```

Running the query will show you the logs (within the specified `Time range`) in a table layout including columns for the logger name, the module that logged the message and the corresponding line in the code.

You can further filter the log messages on the Azure portal.
For example

```text
AppTraces
| extend logger_name = tostring(Properties.logger_name)
| extend module = tostring(Properties.module)
| extend line_number = tostring(Properties.lineNumber)
| where module == "main"
| where Message has "Starting server"
```

The log levels used with the Python `Logger` correspond to `severityLevel` in `traces` on the Azure portal. `severityLevel` uses integer numbers. For convenience, these numbers can be easily substituted with the more familiar corresponding log levels by adding the following line to the `kusto` query:

```text
| extend log_level = case(severityLevel == 1, "INFO", severityLevel == 2, "WARNING", severityLevel == 3,"ERROR", "UNKNOWN")
```
