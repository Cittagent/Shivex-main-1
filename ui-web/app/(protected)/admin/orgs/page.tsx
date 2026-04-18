"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authApi, type TenantProfile } from "@/lib/authApi";
import { PageHeader, SectionCard } from "@/components/ui/page-scaffold";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CreateOrgModal } from "@/components/auth/CreateOrgModal";
import { formatIST } from "@/lib/utils";

function OrganizationSkeletonRow({ index }: { index: number }) {
  return (
    <TableRow key={`skeleton-${index}`} className="animate-pulse">
      <TableCell><div className="h-4 w-36 rounded bg-[var(--surface-2)]" /></TableCell>
      <TableCell><div className="h-4 w-28 rounded bg-[var(--surface-2)]" /></TableCell>
      <TableCell><div className="h-6 w-20 rounded-full bg-[var(--surface-2)]" /></TableCell>
      <TableCell><div className="h-4 w-32 rounded bg-[var(--surface-2)]" /></TableCell>
      <TableCell><div className="h-8 w-16 rounded bg-[var(--surface-2)]" /></TableCell>
    </TableRow>
  );
}

export default function AdminOrgsPage() {
  const router = useRouter();
  const [orgs, setOrgs] = useState<TenantProfile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [updatingOrgId, setUpdatingOrgId] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function load(): Promise<void> {
      setIsLoading(true);
      setError(null);
      try {
        const orgList = await authApi.listTenants();
        if (isMounted) {
          setOrgs(orgList);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : "Failed to load organisations");
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      isMounted = false;
    };
  }, []);

  async function handleToggleOrg(org: TenantProfile): Promise<void> {
    setUpdatingOrgId(org.id);
    setError(null);
    try {
      const updated = org.is_active ? await authApi.suspendTenant(org.id) : await authApi.reactivateTenant(org.id);
      setOrgs((current) => current.map((row) => (row.id === updated.id ? updated : row)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update organisation status");
    } finally {
      setUpdatingOrgId(null);
    }
  }

  return (
    <>
      <div className="space-y-5">
        <PageHeader
          title="Organisations"
          subtitle="Create and manage the tenant workspaces that power FactoryOPS deployments."
          actions={(
            <Button onClick={() => setIsCreateOpen(true)}>
              New Organisation
            </Button>
          )}
        />

        <SectionCard
          title="Organisation directory"
          subtitle="Each organisation contains its own plants, users, and operational footprint."
        >
          {error ? (
            <div className="rounded-2xl border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] px-4 py-3 text-sm text-[var(--tone-danger-text)]">
              {error}
            </div>
          ) : null}

          {isLoading ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Array.from({ length: 4 }).map((_, index) => (
                  <OrganizationSkeletonRow key={index} index={index} />
                ))}
              </TableBody>
            </Table>
          ) : orgs.length === 0 ? (
            <EmptyState message="No organisations yet. Create one to get started." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Slug</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orgs.map((org) => (
                  <TableRow key={org.id}>
                    <TableCell className="font-medium">{org.name}</TableCell>
                    <TableCell className="font-mono text-xs text-[var(--text-secondary)]">{org.slug}</TableCell>
                    <TableCell>
                      <Badge variant={org.is_active ? "success" : "error"}>
                        {org.is_active ? "Active" : "Suspended"}
                      </Badge>
                    </TableCell>
                    <TableCell>{formatIST(org.created_at, "Unknown")}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant={org.is_active ? "danger" : "outline"}
                          size="sm"
                          disabled={updatingOrgId === org.id}
                          isLoading={updatingOrgId === org.id}
                          onClick={() => void handleToggleOrg(org)}
                        >
                          {org.is_active ? "Suspend" : "Reactivate"}
                        </Button>
                        <Link href={`/admin/tenants/${org.id}`}>
                          <Button variant="outline" size="sm">View</Button>
                        </Link>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </SectionCard>
      </div>

      <CreateOrgModal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onSuccess={(newOrg) => {
          setOrgs((current) => [newOrg, ...current]);
          router.push(`/admin/tenants/${newOrg.id}`);
        }}
      />
    </>
  );
}
