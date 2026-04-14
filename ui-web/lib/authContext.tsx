"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
  type ReactElement,
} from "react";
import { authApi, subscribeToAuthStateChange, tokenStore, type MeResponse, type UserRole } from "@/lib/authApi";
import { initializeTenantStore } from "@/lib/tenantStore";

interface AuthContextValue {
  me: MeResponse | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasRole: (...roles: UserRole[]) => boolean;
  refetchMe: () => Promise<void>;
}

const defaultValue: AuthContextValue = {
  me: null,
  isLoading: true,
  isAuthenticated: false,
  login: async () => {
    throw new Error("AuthProvider is not mounted");
  },
  logout: async () => {
    throw new Error("AuthProvider is not mounted");
  },
  hasRole: () => false,
  refetchMe: async () => {
    throw new Error("AuthProvider is not mounted");
  },
};

export const AuthContext = createContext<AuthContextValue>(defaultValue);

export function AuthProvider({ children }: { children: ReactNode }): ReactElement {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  async function refetchMe(): Promise<void> {
    const freshMe = await authApi.getMe();
    tokenStore.setMeData(freshMe);
    setMe(freshMe);
  }

  useEffect(() => {
    let active = true;

    async function restore(): Promise<void> {
      setIsLoading(true);
      initializeTenantStore();

      const accessToken = tokenStore.getAccessToken();
      const refreshToken = tokenStore.getRefreshToken();
      const cached = tokenStore.getMeData();
      if (cached && active && (accessToken || refreshToken)) {
        setMe(cached);
      }

      try {
        const freshMe = await authApi.getMe();
        if (active) {
          setMe(freshMe);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "Request failed";
        if (message === "SESSION_EXPIRED" || message.includes("401")) {
          const refreshed = await authApi.refreshAccessToken();
          if (refreshed) {
            try {
              const freshMe = await authApi.getMe();
              if (active) {
                setMe(freshMe);
              }
            } catch {
              tokenStore.clearAll();
              if (active) {
                setMe(null);
              }
            }
          } else {
            tokenStore.clearAll();
            if (active) {
              setMe(null);
            }
          }
        } else {
          tokenStore.clearAll();
          if (active) {
            setMe(null);
          }
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    }

    void restore();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    return subscribeToAuthStateChange((nextMe) => {
      setMe(nextMe);
      if (nextMe === null) {
        setIsLoading(false);
      }
    });
  }, []);

  const value: AuthContextValue = {
    me,
    isLoading,
    isAuthenticated: Boolean(me),
    login: async (email: string, password: string) => {
      const result = await authApi.login(email, password);
      setMe(result);
    },
    logout: async () => {
      await authApi.logout();
      setMe(null);
    },
    hasRole: (...roles: UserRole[]) => {
      const role = me?.user.role;
      return role ? roles.includes(role) : false;
    },
    refetchMe,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
