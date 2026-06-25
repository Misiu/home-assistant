"""Helpers for caching OpenDisplay device metadata in config entries."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from types import NoneType, UnionType
from typing import Any, cast, get_args, get_origin, get_type_hints

from opendisplay.models.config import GlobalConfig

_BYTES_MARKER = "__bytes__"


def serialize_device_config(device_config: GlobalConfig) -> dict[str, Any]:
    """Serialize a GlobalConfig to JSON-safe data."""
    serialized = _serialize_value(device_config)
    if not isinstance(serialized, dict):
        raise TypeError("Serialized GlobalConfig must be a dict")
    return serialized


def deserialize_device_config(data: Mapping[str, Any]) -> GlobalConfig:
    """Deserialize a GlobalConfig from JSON-safe data."""
    config = _deserialize_value(GlobalConfig, data)
    if not isinstance(config, GlobalConfig):
        raise TypeError("Deserialized value is not a GlobalConfig")
    return config


def _serialize_value(value: Any) -> Any:
    """Serialize dataclass-based config values recursively."""
    if is_dataclass(value):
        return {
            field.name: _serialize_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, bytes):
        return {_BYTES_MARKER: value.hex()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def _deserialize_value(annotation: Any, value: Any) -> Any:
    """Deserialize a config value recursively."""
    if value is None:
        return None

    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return [_deserialize_value(item_type, item) for item in value]

    if origin is UnionType:
        for arg in get_args(annotation):
            if arg is NoneType:
                continue
            try:
                return _deserialize_value(arg, value)
            except KeyError, TypeError, ValueError:
                continue
        raise TypeError(f"Unsupported union value for {annotation!r}")

    if annotation is bytes:
        if not isinstance(value, Mapping) or _BYTES_MARKER not in value:
            raise TypeError("Expected encoded bytes mapping")
        marker_value = value[_BYTES_MARKER]
        if not isinstance(marker_value, str):
            raise TypeError("Expected hex string for encoded bytes")
        return bytes.fromhex(marker_value)

    if is_dataclass(annotation):
        if not isinstance(value, Mapping):
            raise TypeError("Expected mapping for dataclass value")
        type_hints = get_type_hints(annotation)
        annotation_cls = cast(type[Any], annotation)
        return annotation_cls(
            **{
                field.name: _deserialize_value(
                    type_hints[field.name], value[field.name]
                )
                for field in fields(annotation)
            }
        )

    return value
