# Extra CA certificates (local development only)

Any `*.crt` file (PEM) in this folder is added to the backend container's trust store at build time.

Use this when antivirus or a corporate proxy inspects HTTPS traffic (e.g. Kaspersky
"encrypted connections scan") and the container rejects its certificate with
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`.

`*.crt` files are git-ignored — they are specific to your machine.
