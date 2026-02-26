"""Plugin manifest schema for Rigovo ecosystem plugins."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ConnectorSpec(BaseModel):
    """Inbound/outbound integration connector (Slack, Teams, n8n, etc.)."""

    id: str
    provider: str
    kind: str = "webhook"  # webhook|api|socket
    inbound_events: list[str] = Field(default_factory=list)
    outbound_actions: list[str] = Field(default_factory=list)
    config_schema: dict[str, object] = Field(default_factory=dict)


class SkillSpec(BaseModel):
    """Skill package exposed by a plugin."""

    id: str
    description: str
    path: str  # relative path inside plugin package


class MCPServerSpec(BaseModel):
    """MCP server exposed by plugin."""

    id: str
    transport: str = "stdio"  # stdio|sse|http
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""


class HookSpec(BaseModel):
    """Lifecycle hook executed by plugin."""

    event: str
    handler: str  # import path or script path
    timeout_seconds: int = 10


class ActionSpec(BaseModel):
    """Declarative action interface for a plugin."""

    id: str
    description: str
    input_schema: dict[str, object] = Field(default_factory=dict)
    output_schema: dict[str, object] = Field(default_factory=dict)
    requires_approval: bool = False


class PluginManifest(BaseModel):
    """Top-level plugin manifest."""

    schema_version: str = "rigovo.plugin.v1"
    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    homepage: str = ""
    enabled: bool = True
    trust_level: str = "community"  # community|verified|internal

    capabilities: list[str] = Field(default_factory=list)
    connectors: list[ConnectorSpec] = Field(default_factory=list)
    skills: list[SkillSpec] = Field(default_factory=list)
    mcp_servers: list[MCPServerSpec] = Field(default_factory=list)
    hooks: list[HookSpec] = Field(default_factory=list)
    actions: list[ActionSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_capabilities(self) -> "PluginManifest":
        if self.trust_level not in {"community", "verified", "internal"}:
            raise ValueError(
                "trust_level must be one of: community, verified, internal"
            )
        implied: set[str] = set()
        if self.connectors:
            implied.add("connector")
        if self.skills:
            implied.add("skill")
        if self.mcp_servers:
            implied.add("mcp")
        if self.hooks:
            implied.add("hook")
        if self.actions:
            implied.add("action")
        if implied and not self.capabilities:
            self.capabilities = sorted(implied)
        return self
