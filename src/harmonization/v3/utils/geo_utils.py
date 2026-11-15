from math import isfinite, sqrt

from pyproj import CRS, Transformer
from shapely import transform as shapely_transform
from shapely.geometry import Point


def build_conservative_envelope(
    longitude: float,
    latitude: float,
    scan_km: float,
    track_km: float,
):
    """
    Construct an orientation-independent circular screening envelope.

    Its radius is half the diagonal of a rectangle with scan_km and
    track_km side lengths. It is NOT the actual sensor pixel footprint.
    """
    values = (longitude, latitude, scan_km, track_km)

    if not all(isfinite(value) for value in values):
        raise ValueError("Envelope inputs must all be finite.")

    if not -180.0 <= longitude <= 180.0:
        raise ValueError("Longitude outside [-180, 180].")

    if not -90.0 <= latitude <= 90.0:
        raise ValueError("Latitude outside [-90, 90].")

    if scan_km <= 0 or track_km <= 0:
        raise ValueError("Scan and track dimensions must be positive.")

    radius_m = 500.0 * sqrt(scan_km**2 + track_km**2)

    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} "
        "+datum=WGS84 +units=m +no_defs +type=crs"
    )

    to_wgs84 = Transformer.from_crs(
        local_crs,
        CRS.from_epsg(4326),
        always_xy=True,
    ).transform

    local_circle = Point(0.0, 0.0).buffer(
        radius_m,
        quad_segs=32,
    )

    geographic_envelope = shapely_transform(
        local_circle,
        to_wgs84,
        interleaved=False,
    )

    if geographic_envelope.is_empty or not geographic_envelope.is_valid:
        raise ValueError("Constructed envelope is empty or invalid.")

    return geographic_envelope, radius_m / 1000.0
