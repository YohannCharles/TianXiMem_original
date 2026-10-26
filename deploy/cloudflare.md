# Cloudflare Tunnel Ingress

TianXiMem can be exposed through a Cloudflare Tunnel without adding a second
application or profile. The tunnel forwards `/add`, `/search`, and `/health` to
the local application port.

## Configuration

Set deployment-specific values outside this repository. The example below uses
placeholders; keep the real tunnel ID, hostname, credential path, and local port
in your private operations configuration.

```yaml
tunnel: <TUNNEL_ID>
credentials-file: <ABSOLUTE_CREDENTIALS_PATH>
no-autoupdate: true
protocol: http2

ingress:
  - hostname: <PUBLIC_HOSTNAME>
    service: http://127.0.0.1:<APP_PORT>
  - service: http_status:404
```

The credentials file is secret. Never commit it.

## Checks

```bash
cloudflared --config <ROUTE_CONFIG> tunnel ingress validate
cloudflared --config <ROUTE_CONFIG> tunnel ingress rule https://<PUBLIC_HOSTNAME>/add
curl --fail --show-error http://127.0.0.1:<APP_PORT>/health
curl --fail --show-error https://<PUBLIC_HOSTNAME>/health
```

If the host application port changes, update the tunnel service URL.

## Constraints

- The service itself has no authentication; the tunnel does not add application identity.
- Add TLS and authentication at the ingress or reverse proxy before exposing data.
- Cloudflare Browser Integrity Check may reject clients with an empty or unusual User-Agent.
- Cloudflare edge timeouts apply. Verify long Add and Search requests before full evaluation runs.
