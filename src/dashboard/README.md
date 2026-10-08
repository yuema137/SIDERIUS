# Browse experiment results

The dashboard reads saved experiment records and displays scores and model
information. It is a read-only observer; starting it does not start training.
The supported data source is local JSON records. PostgreSQL remains a stub.

Start with the [dashboard guide](../../docs/guides/dashboard.md) to select a
results directory and understand the current configuration and display limits.
The server's default bind address is `0.0.0.0`; choose `--host 127.0.0.1` when
you want access only from the local machine.

| Need | Reference |
| --- | --- |
| Inspect settings, routes and tests | [Dashboard contract](dashboard-contract.md) |
| Understand record loading | [Data sources](data_sources/README.md) |
| Work on the HTTP interface | [API](api/README.md) |

The [dated UX audit](../../docs/agent-reference/dashboard_ux_audit.md) records
known issues and candidate fixes. It does not certify that those fixes landed.
