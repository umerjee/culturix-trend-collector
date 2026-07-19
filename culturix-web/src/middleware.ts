import { createServerClient } from "@supabase/ssr";
import type { CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

// Supabase's free tier can pause the project after inactivity, and even when
// awake, auth calls can occasionally be slow. Without a timeout, a hung
// supabase.auth.getUser() call blocks this middleware indefinitely, which
// Vercel eventually kills with a 504 MIDDLEWARE_INVOCATION_TIMEOUT — taking
// down every protected route at once. Cap the auth check so a slow/paused
// Supabase degrades to "treat as logged out" instead of a full outage.
const AUTH_CHECK_TIMEOUT_MS = 4000;

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
          // Forward cookies to the request (no options — request cookies are plain name/value)
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          supabaseResponse = NextResponse.next({ request });
          // Set on the response with full options (httpOnly, sameSite, etc.)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options as any)
          );
        },
      },
    }
  );

  const user = await Promise.race([
    supabase.auth.getUser().then(({ data }) => data.user),
    new Promise<null>((resolve) => {
      setTimeout(() => {
        console.error(
          `[middleware] Supabase auth check timed out after ${AUTH_CHECK_TIMEOUT_MS}ms — treating as logged out`
        );
        resolve(null);
      }, AUTH_CHECK_TIMEOUT_MS);
    }),
  ]).catch((err) => {
    console.error("[middleware] Supabase auth check failed:", err);
    return null;
  });

  const path = request.nextUrl.pathname;
  const isProtected =
    path.startsWith("/dashboard") || path.startsWith("/settings");
  const isAuthPage = path === "/signup" || path === "/login";

  if (!user && isProtected) {
    return NextResponse.redirect(new URL("/signup", request.url));
  }

  if (user && isAuthPage) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/settings/:path*",
    "/signup",
    "/login",
    "/onboarding/:path*",
  ],
};
