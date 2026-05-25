# tuskr-mcp-server

Implements a Model Context Protocol (MCP) server for the [Tuskr REST API](https://tuskr.app/kb/latest/api)

Built on the FastMCP Python SDK.  
Supports access token authentication.

## Installation

### Environment variables / `.env` file

Set up environment variables or configure the `.env` file using the `.env.example` template.

The following environment variables are supported:

```
TUSKR_TENANT_ID=<your tenant id>
TUSKR_ACCESS_TOKEN=<your access token>
```
(this doc desc https://tuskr.app/kb/latest/api)

and optionally 
```
MCP_TRANSPORT=<transport type: http or stdio>
MCP_HOST=<host for HTTP transport>
MCP_PORT=<port for HTTP transport>
```

## Command Line Parameters

The MCP server supports the following command line parameters:

- `--transport`: Transport type for the MCP server. Options: `http` (default) or `stdio`
- `--host`: Host address for HTTP transport (default: `0.0.0.0`)
- `--port`: Port number for HTTP transport (default: `8000`)

**Note**: The `--host` and `--port` parameters are only applicable when using the `http` transport.

### Default Values

- **Transport**: `http` (can be overridden with `MCP_TRANSPORT` environment variable)
- **Host**: `0.0.0.0` (can be overridden with `MCP_HOST` environment variable)
- **Port**: `8000` (can be overridden with `MCP_PORT` environment variable)

## Connect from client

### HTTP Transport (Default)

Use the following template to connect the server via HTTP:

```
{
  "mcpServers": {
    "tuskr": {
      "transport": "http",
      "url": "http://<your-mcp-dns-or-ip>/mcp/",
      "headers": {
        "Authorization": "Bearer <your access token>",
        "Tenant-ID": "<your-tuskr-tenant-id>"
      }
    }
  }
}
```

The `Authorization` is mandatory.

The `Tenant-ID` is not required and can be set on the server side using the `TUSKR_TENANT_ID` env variable. It's convenient in case you have a single MCP Server for your organization.

### Migrating from TUSKR_ACCOUNT_ID

Earlier versions of this server used the env var `TUSKR_ACCOUNT_ID` and the HTTP header
`Account-ID`. These continue to work, but emit a deprecation warning. Tuskr's own
documentation and UI consistently use the term "Tenant ID" (it is part of the REST URL
path: `/api/tenant/<tenant-id>/`), so the preferred names are now `TUSKR_TENANT_ID` and
the `Tenant-ID` HTTP header. Both names will be supported until a future major version
removes the legacy names.

To migrate an existing config, replace `TUSKR_ACCOUNT_ID` with `TUSKR_TENANT_ID`; no
other changes are required.

### stdio Transport (for local development)

For local development and integration with tools like `uvx`, use the `stdio` transport:

```
{
  "mcpServers": {
    "tuskr": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["tuskr-mcp-server", "--transport", "stdio"]
    }
  }
}
```

or use `uv` with source code:

```
{
  "mcpServers": {
    "tuskr": {
      "transport": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/your/tuskr-mcp-server",
        "run",
        "src/main.py",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

## Development

### Setup

1. Clone repo
2. Install development dependencies:
`uv sync --dev`
3. Create `.env` from `.env.example`

### Running MCP service

#### HTTP Transport (Default)
```
uv run --env-file .env src/main.py
```

#### stdio Transport (for local development)
```
uv run --env-file .env src/main.py --transport stdio
```

#### Custom Host/Port
```
uv run --env-file .env src/main.py --host 127.0.0.1 --port 9000
```

### Running tests

The project uses pytest for testing. The following command will run all tests

```
uv run pytest -vsx
```

### Running linters

The project uses the `ruff` tool as a linter.

The following command allows to run linter

```
uv run ruff check
```

and this command allow to fix formatting

```
uv run ruff format
```

### Dockerization

The following command allows to build a docker image
```
docker build -t tuskr-mcp .
```

and then you can run it using the
```
docker run -it tuskr-mcp
```