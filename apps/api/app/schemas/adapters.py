"""HTTP schemas for platform adapter capability declarations.

These mirror the in-process ``AdapterDescriptor`` dataclass so the web UI can
render each adapter's capability matrix (which platform differences live in the
adapter, per the AGENTS.md design constraints).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class AdapterConfigFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    required: bool
    secret: bool = False
    description: str | None = None


class AdapterDescriptorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    implementation_status: str
    # Capability enum value -> supported boolean, e.g. {"PUBLIC_PROFILE": true}
    capabilities: dict[str, bool]
    config_fields: list[AdapterConfigFieldRead]
    source_kinds: list[str]


def build_adapter_descriptor_read(descriptor: Any) -> AdapterDescriptorRead:
    """Serialize an in-process ``AdapterDescriptor`` into its HTTP schema.

    Capability keys are taken from the ``AdapterCapability`` enum ``.value``
    (StrEnum) so the wire format stays stable and human-readable.
    """
    return AdapterDescriptorRead(
        key=descriptor.key,
        name=descriptor.name,
        implementation_status=descriptor.implementation_status,
        capabilities={
            capability.value: supported
            for capability, supported in descriptor.capabilities.items()
        },
        config_fields=[
            AdapterConfigFieldRead(
                key=field.key,
                label=field.label,
                required=field.required,
                secret=field.secret,
                description=field.description,
            )
            for field in descriptor.config_fields
        ],
        source_kinds=sorted(descriptor.source_kinds),
    )
