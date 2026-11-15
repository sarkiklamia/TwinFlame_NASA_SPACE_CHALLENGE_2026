def candidate_evaluation_status():
    # Phase 4A records evidence; it does not confirm correspondences.
    return "candidate_evaluated"


def geometry_evidence_status(geometry_a, geometry_b):
    has_a = geometry_a.spatial_envelope is not None
    has_b = geometry_b.spatial_envelope is not None

    if has_a and has_b:
        return "both_screening_envelopes_available"
    if has_a or has_b:
        return "one_screening_envelope_available"
    return "no_screening_envelopes_available"
