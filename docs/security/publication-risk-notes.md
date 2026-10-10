<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. Publication lessons

## 1.1. Maintained source and clean distribution

A maintained source can register optional components while a clean Core omits them. An installer must validate the actual canonical rule bodies and derive rule summaries from the maintained index, without treating local component registration as a conflicting rule body. Preserve source registration and reject genuinely modified authoritative rules before writing. Test installation, source preservation, mismatch rejection, and rollback separately.

## 1.2. Remote references

Ordinary branch and tag checks do not cover every Git reference. Retain independently observed extra references unless their removal is separately authorized. A strict checker rejecting a notes reference remains a failure of that strict audit; matching release bytes or successful installation does not convert it into a pass.
