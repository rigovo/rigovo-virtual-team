"""Quality gate builder — constructs gates from config and domain plugins."""

from __future__ import annotations

from rigovo.config import AppConfig
from rigovo.domain.entities.quality import ViolationSeverity
from rigovo.domain.interfaces.domain_plugin import DomainPlugin
from rigovo.domain.interfaces.quality_gate import QualityGate
from rigovo.infrastructure.quality.rigour_gate import (
    RigourGateConfig,
    RigourQualityGate,
)

SEVERITY_MAP = {
    "error": ViolationSeverity.ERROR,
    "warning": ViolationSeverity.WARNING,
    "info": ViolationSeverity.INFO,
}


class QualityGateBuilder:
    """
    Builds quality gates from rigovo.yml and domain plugins.

    Priority:
    1. rigovo.yml quality.gates overrides (user-configurable thresholds)
    2. Domain plugin gate configs (sensible defaults)
    3. Rigour CLI when available, built-in AST fallback otherwise
    """

    def __init__(
        self,
        config: AppConfig,
        domains: dict[str, DomainPlugin],
    ) -> None:
        self._config = config
        self._domains = domains

    def build(self) -> list[QualityGate]:
        """Build all configured quality gates."""
        yml_quality = self._config.yml.quality
        configs = self._configs_from_yml(yml_quality)
        configs = self._merge_domain_configs(configs)

        return [RigourQualityGate(
            gate_configs=configs,
            rigour_binary=yml_quality.rigour_binary,
            timeout_seconds=yml_quality.rigour_timeout,
        )]

    def _configs_from_yml(self, yml_quality) -> list[RigourGateConfig]:
        """Build gate configs from rigovo.yml overrides."""
        configs: list[RigourGateConfig] = []
        for gate_id, gate_override in yml_quality.gates.items():
            configs.append(
                RigourGateConfig(
                    gate_id=gate_id,
                    name=gate_id.replace("-", " ").title(),
                    threshold=gate_override.threshold,
                    severity=SEVERITY_MAP.get(
                        gate_override.severity, ViolationSeverity.ERROR,
                    ),
                    enabled=gate_override.enabled,
                )
            )
        return configs

    def _merge_domain_configs(
        self, configs: list[RigourGateConfig],
    ) -> list[RigourGateConfig]:
        """Add domain plugin gates that aren't already configured."""
        existing_ids = {c.gate_id for c in configs}
        for domain in self._domains.values():
            for gate_cfg in domain.get_quality_gates():
                if gate_cfg.gate_id not in existing_ids:
                    configs.append(
                        RigourGateConfig(
                            gate_id=gate_cfg.gate_id,
                            name=gate_cfg.name,
                            threshold=gate_cfg.threshold,
                        )
                    )
        return configs
