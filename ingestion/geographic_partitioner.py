
"""Geographic partitioning for FIRMS Area API requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.api_config import load_sources_yaml

WORLD_BOUNDS = (-180.0, -90.0, 180.0, 90.0)


@dataclass(frozen=True)
class GeoPartition:
    """One geographic request area."""

    partition_id: str
    bbox: str


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    if value.strip().lower() == "world":
        return WORLD_BOUNDS

    try:
        west, south, east, north = map(
            float,
            value.split(","),
        )
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"Invalid bounding box: {value!r}"
        ) from exc

    if not (
        -180 <= west < east <= 180
        and -90 <= south < north <= 90
    ):
        raise ValueError(
            f"Invalid geographic bounds: {value!r}"
        )

    return west, south, east, north


def _format_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
) -> str:
    return ",".join(
        f"{coordinate:g}"
        for coordinate in (west, south, east, north)
    )


def _generate_grid(
    bounds: tuple[float, float, float, float],
    tile_size: float,
) -> list[GeoPartition]:
    west, south, east, north = bounds

    if tile_size <= 0:
        raise ValueError("tile_size_degrees must be positive.")

    partitions: list[GeoPartition] = []
    index = 0

    latitude = south

    while latitude < north:
        tile_north = min(latitude + tile_size, north)

        longitude = west

        while longitude < east:
            tile_east = min(longitude + tile_size, east)

            bbox = _format_bbox(
                longitude,
                latitude,
                tile_east,
                tile_north,
            )

            partitions.append(
                GeoPartition(
                    partition_id=f"tile_{index:04d}",
                    bbox=bbox,
                )
            )

            index += 1
            longitude = tile_east

        latitude = tile_north

    return partitions


def get_partitions(
    yaml_data: dict[str, Any] | None = None,
) -> list[GeoPartition]:
    """Build geographic partitions from sources.yaml."""

    data = yaml_data or load_sources_yaml()
    settings = data.get("partitioning", {})

    bbox_value = settings.get("bbox", "world")
    bounds = _parse_bbox(bbox_value)

    strategy = str(
        settings.get("strategy", "single")
    ).lower()

    if strategy == "single":
        return [
            GeoPartition(
                partition_id="area_0000",
                bbox=_format_bbox(*bounds),
            )
        ]

    if strategy != "grid":
        raise ValueError(
            f"Unsupported partitioning strategy: {strategy!r}"
        )

    tile_size = float(
        settings.get("tile_size_degrees", 30)
    )

    return _generate_grid(bounds, tile_size)
