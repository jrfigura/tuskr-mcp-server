"""Resolution of the Tuskr tenant ID and access token for a tool call.

Every tool needs the same two values by the same precedence, so the rule lives
here once rather than being restated per tool.
"""

import os


async def resolve(ctx):
    """Return the (tenant_id, access_token) pair to use for this request.

    HTTP headers win over the environment: `UserTokenHandler` puts them on the
    context, and in stdio mode it sets both to None so the env vars are used
    instead. TUSKR_ACCOUNT_ID is the deprecated spelling of TUSKR_TENANT_ID and
    is only consulted when the preferred name is unset.
    """
    tenant_id = (
        (await ctx.get_state("ext_tenant_id"))
        or os.environ.get("TUSKR_TENANT_ID")
        or os.environ.get("TUSKR_ACCOUNT_ID")
    )
    access_token = (await ctx.get_state("ext_access_token")) or os.environ.get(
        "TUSKR_ACCESS_TOKEN"
    )
    return tenant_id, access_token
