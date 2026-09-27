# Serve CandyConc behind a reverse proxy

CandyConc serves the web interface and the HTTP API from the same address,
so a reverse proxy only has to forward every path to it. The proxy adds a
host name and TLS, and CandyConc itself keeps listening on the loopback
address. This guide configures such a proxy.

## Before you begin

- CandyConc in multi-user mode, see
  [Run CandyConc for several users](multi-user-server.md).
- A web server that can act as a reverse proxy and forward WebSocket
  connections, with a certificate for your host name. The example uses the
  Apache HTTP Server 2.4.

## What the proxy must forward

- Every path to CandyConc, including `/` for the interface and `/api/` for
  the API.
- WebSocket connections. Analysis jobs report their progress over
  `/api/v1/ws/analysis/...`, which the browser opens as a WebSocket.
- Streamed responses without buffering. Searches and copilot answers stream
  their results as they are computed.
- The original `Host` header. CandyConc checks it against
  `CANDYCONC_TRUSTED_HOSTS` and rejects other host names with the status 400
  and the message `Untrusted Host header`.

## Configure the proxy

1. Start CandyConc in multi-user mode on the loopback address, with your host
   name in the list of trusted hosts. Replace `corpus.example.org` with your
   host name:

   ```bash
   export CANDYCONC_TRUSTED_HOSTS=corpus.example.org,localhost,127.0.0.1
   candy --host 127.0.0.1 --port 8010
   ```

2. Configure the proxy. For Apache, with `mod_proxy`, `mod_proxy_http`, and
   `mod_proxy_wstunnel` loaded, the forwarding part of the virtual host is:

   ```apache
   ProxyPreserveHost On
   ProxyPass "/" "http://127.0.0.1:8010/" upgrade=websocket
   ProxyPassReverse "/" "http://127.0.0.1:8010/"
   ```

   Add the TLS settings of your server to the same virtual host.

3. Reload the web server and open `https://corpus.example.org/`.

The interface asks for sign-in. After signing in, searches, analyses, and
analysis jobs work through the proxy. A request through the proxy with a
host name that is not in `CANDYCONC_TRUSTED_HOSTS` is rejected with the
status 400.

## Check the forwarding

With the proxy on `corpus.example.org`, this request returns
`{"status":"ok","engine":"fast-index"}`:

```bash
curl -s https://corpus.example.org/api/v1/health
```

## Other web servers

For nginx, Caddy, or another server, configure the same four points: forward
every path, pass WebSocket upgrades, do not buffer streamed responses, and
keep the `Host` header.

## Result

CandyConc is reachable under your host name with TLS, and the server itself
stays bound to the loopback address. The settings that control host names,
sign-in, and limits are listed in [Configuration reference](../../reference/configuration.md).
