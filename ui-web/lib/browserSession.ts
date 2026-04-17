"use client";

type AccessTokenClaims = {
  role?: string;
  tenant_id?: string | null;
  exp?: number;
};

const LEGACY_ACCESS_TOKEN_KEY = "factoryops_access_token";
const LEGACY_REFRESH_TOKEN_KEY = "factoryops_refresh_token";

let accessToken: string | null = null;

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function hydrateLegacyAccessToken(): void {
  if (accessToken || !isBrowser()) {
    return;
  }

  const legacyToken = window.sessionStorage.getItem(LEGACY_ACCESS_TOKEN_KEY);
  if (legacyToken) {
    accessToken = legacyToken;
  }
  window.sessionStorage.removeItem(LEGACY_ACCESS_TOKEN_KEY);
  window.sessionStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
}

function decodeClaims(token: string | null): AccessTokenClaims | null {
  if (!token) {
    return null;
  }

  try {
    const parts = token.split(".");
    if (parts.length !== 3) {
      return null;
    }
    return JSON.parse(atob(parts[1])) as AccessTokenClaims;
  } catch {
    return null;
  }
}

export function getAccessToken(): string | null {
  hydrateLegacyAccessToken();
  return accessToken;
}

export function getAccessTokenClaims(): AccessTokenClaims | null {
  hydrateLegacyAccessToken();
  return decodeClaims(accessToken);
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  if (isBrowser()) {
    window.sessionStorage.removeItem(LEGACY_ACCESS_TOKEN_KEY);
    window.sessionStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
  }
}

export function clearAccessToken(): void {
  accessToken = null;
  if (isBrowser()) {
    window.sessionStorage.removeItem(LEGACY_ACCESS_TOKEN_KEY);
    window.sessionStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
  }
}
