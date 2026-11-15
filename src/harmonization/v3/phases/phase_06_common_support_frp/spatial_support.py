import math
from collections.abc import Iterable

from pyproj import CRS, Transformer

from ...config.frp_support import (
    SpatialSupportConfig,
    build_spatial_support_experiments,
)
from ...contracts.frp import (
    SpatialSupportAssignment,
    SpatialSupportExperimentResult,
)


def _extract_geometry_results(source) -> tuple:
    if hasattr(source, "results"):
        return tuple(source.results)
    if isinstance(source, Iterable):
        return tuple(source)
    raise TypeError("Expected Phase02Result or iterable of geometry results")


def grid_cell_indices(
    projected_x_m: float,
    projected_y_m: float,
    grid_resolution_km: float,
) -> tuple[int, int]:
    values = (projected_x_m, projected_y_m, grid_resolution_km)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Grid coordinates and resolution must be finite")
    if grid_resolution_km <= 0:
        raise ValueError("Grid resolution must be positive")

    cell_size_m = grid_resolution_km * 1000.0

    return (
        math.floor(projected_x_m / cell_size_m),
        math.floor(projected_y_m / cell_size_m),
    )


def assign_spatial_support(
    phase02_result,
    config: SpatialSupportConfig,
) -> tuple[SpatialSupportAssignment, ...]:
    geometry_results = _extract_geometry_results(phase02_result)

    source_crs = CRS.from_epsg(4326)
    target_crs = CRS.from_user_input(config.projection_crs)
    area = target_crs.area_of_use

    if area is None:
        raise ValueError("Target CRS must declare a geographic area of use")

    transformer = Transformer.from_crs(
        source_crs,
        target_crs,
        always_xy=True,
    )

    assignments = []
    seen = set()

    for geometry_result in geometry_results:
        qc_result = geometry_result.qc_result

        if not qc_result.eligible_for_frp_analysis:
            continue

        observation = qc_result.observation
        detection_id = observation.detection_id
        platform = observation.platform
        latitude = observation.latitude
        longitude = observation.longitude

        if not detection_id or not platform:
            raise ValueError("FRP-eligible observation has missing identity")

        identity = (platform, detection_id)
        if identity in seen:
            raise ValueError(f"Duplicate observation identity: {identity}")
        seen.add(identity)

        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90.0 <= latitude <= 90.0
            and -180.0 <= longitude <= 180.0
        ):
            raise ValueError(f"Invalid coordinates for {identity}")

        if not (area.south <= latitude <= area.north):
            raise ValueError(
                f"Latitude {latitude} is outside {config.projection_crs} "
                f"area of use [{area.south}, {area.north}]"
            )

        if not (area.west <= longitude <= area.east):
            raise ValueError(
                f"Longitude {longitude} is outside {config.projection_crs} "
                f"area of use [{area.west}, {area.east}]"
            )

        x_m, y_m = transformer.transform(
            longitude,
            latitude,
            errcheck=True,
        )

        if not (math.isfinite(x_m) and math.isfinite(y_m)):
            raise ValueError(f"Projection failed for {identity}")

        cell_x, cell_y = grid_cell_indices(
            x_m,
            y_m,
            config.grid_resolution_km,
        )

        resolution_m = int(round(config.grid_resolution_km * 1000))
        cell_id = (
            f"{config.projection_crs.replace(':', '')}_"
            f"{resolution_m}m_{cell_x}_{cell_y}"
        )

        assignments.append(
            SpatialSupportAssignment(
                detection_id=detection_id,
                platform=platform,
                cell_id=cell_id,
                grid_resolution_km=config.grid_resolution_km,
                cell_x=cell_x,
                cell_y=cell_y,
                projected_x_m=x_m,
                projected_y_m=y_m,
            )
        )

    return tuple(assignments)


def run_spatial_support_experiments(phase02_result):
    results = []

    for config in build_spatial_support_experiments():
        assignments = assign_spatial_support(phase02_result, config)

        results.append(
            SpatialSupportExperimentResult(
                grid_resolution_km=config.grid_resolution_km,
                assignments=assignments,
            )
        )

    return tuple(results)
