/**
 * Cloudflare Worker — GitHub OAuth Token Exchange Proxy
 *
 * This worker securely exchanges the temporary OAuth authorization code
 * for a GitHub Access Token. The CLIENT_SECRET is stored as a Cloudflare
 * Worker secret and never exposed to the frontend.
 *
 * Deployment:
 *   1. Install Wrangler CLI: npm install -g wrangler
 *   2. Login: wrangler login
 *   3. Set your secrets:
 *        wrangler secret put GITHUB_CLIENT_ID
 *        wrangler secret put GITHUB_CLIENT_SECRET
 *   4. Deploy: wrangler deploy
 *
 * Free tier: 100,000 requests/day — more than enough.
 */

export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const { code } = await request.json();
    if (!code) {
      return new Response(JSON.stringify({ error: "Missing code" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Exchange the temporary code for an access token
    const tokenResponse = await fetch(
      "https://github.com/login/oauth/access_token",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          client_id: env.GITHUB_CLIENT_ID,
          client_secret: env.GITHUB_CLIENT_SECRET,
          code: code,
        }),
      }
    );

    const tokenData = await tokenResponse.json();

    return new Response(JSON.stringify(tokenData), {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};
