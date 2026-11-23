"""Owner decisions shared by the Arabic clinical guard tests and evaluation runner.

Keeps one copy of the reviewed case IDs that no longer count as required
launch blocks, so the reviewed labels in ``arabic_reviewed_cases.json`` stay
as recorded and no test file needs to import another.
"""

#: Reviewed launch blocks that were accepted interim false positives and are
#: now answered normally by owner decision: ar-sore-04 is plainly named DOMS,
#: which the #754 soreness bypass lets through. The reviewed labels stay as
#: recorded.
RESOLVED_ACCEPTED_FALSE_POSITIVES = {"ar-sore-04"}
