# Security reporting

Read [the local security contract](docs/security.md) before changing deployment
boundaries. The writable service is a trusted single-user loopback application;
the public demo is recorded static files. Neither is a production multi-tenant
service. Use current main for fixes; no historical-version support is promised.

For a sensitive issue, use the repository's GitHub **Security → Report a
vulnerability** channel if available. If private reporting is unavailable, open
an issue requesting a private contact without technical exploit details. Never
post credentials, private evaluation data or personal session artifacts. Include
version/commit, affected boundary, impact and a sanitized reproduction in the
private report. There is no guaranteed response time or bug bounty.
