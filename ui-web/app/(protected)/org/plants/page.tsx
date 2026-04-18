"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/authContext";
import { authApi, type PlantProfile } from "@/lib/authApi";
import { PageHeader, SectionCard } from "@/components/ui/page-scaffold";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/EmptyState";
import { CreatePlantModal } from "@/components/auth/CreatePlantModal";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatIST } from "@/lib/utils";

function PlantsSkeleton() {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Location</TableHead>
          <TableHead>Timezone</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 4 }).map((_, index) => (
          <TableRow key={index} className="animate-pulse">
            <TableCell><div className="h-4 w-36 rounded bg-[var(--surface-2)]" /></TableCell>
            <TableCell><div className="h-4 w-40 rounded bg-[var(--surface-2)]" /></TableCell>
            <TableCell><div className="h-4 w-28 rounded bg-[var(--surface-2)]" /></TableCell>
            <TableCell><div className="h-6 w-20 rounded-full bg-[var(--surface-2)]" /></TableCell>
            <TableCell><div className="h-4 w-32 rounded bg-[var(--surface-2)]" /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function OrgPlantsPage() {
  const { me, isLoading: isAuthLoading } = useAuth();
  const router = useRouter();
  const orgId = me?.tenant?.id ?? null;

  const [plants, setPlants] = useState<PlantProfile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [updatingPlantId, setUpdatingPlantId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) {
      return undefined;
    }
    const timer = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!isAuthLoading && !orgId) {
      if (me?.user.role === "super_admin") {
        setError("Super admins should manage plants from the Admin panel for a specific organisation.");
        setIsLoading(false);
      } else {
        router.replace("/machines");
      }
      return;
    }

    if (!isAuthLoading && me?.user.role === "plant_manager") {
      router.replace("/tenant/users");
      return;
    }

    if (!orgId) {
      return;
    }

    const resolvedOrgId = orgId;
    let active = true;
    async function load(): Promise<void> {
      setIsLoading(true);
      setError(null);
      try {
        const plantRows = await authApi.listPlants(resolvedOrgId);
        if (active) {
          setPlants(plantRows);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to load plants");
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [isAuthLoading, me?.user.role, orgId, router]);

  async function handleTogglePlant(plant: PlantProfile): Promise<void> {
    if (!orgId) {
      return;
    }
    setUpdatingPlantId(plant.id);
    setError(null);
    try {
      const updated = plant.is_active
        ? await authApi.deactivatePlant(orgId, plant.id)
        : await authApi.reactivatePlant(orgId, plant.id);
      setPlants((current) => current.map((row) => (row.id === updated.id ? updated : row)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update plant");
    } finally {
      setUpdatingPlantId(null);
    }
  }

  return (
    <>
      <div className="space-y-5">
        <PageHeader
          title="Plants"
          subtitle="Manage the physical factories, buildings, and sites available to your team."
          actions={orgId ? <Button onClick={() => setCreateOpen(true)}>Add Plant</Button> : undefined}
        />

        {error ? (
          <div className="rounded-2xl border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] px-4 py-3 text-sm text-[var(--tone-danger-text)]">
            {error}
          </div>
        ) : null}

        {toast ? (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {toast}
          </div>
        ) : null}

        <SectionCard
          title="Plant directory"
          subtitle={`${plants.length} plant${plants.length === 1 ? "" : "s"} configured for this organisation.`}
        >
          <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            Inactive plants stay readable for history, but they cannot be used in new user assignments or device onboarding.
          </div>
          {isLoading ? (
            <PlantsSkeleton />
          ) : plants.length === 0 ? (
            <EmptyState message="No plants yet. Add a plant to start assigning devices and people." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead>Timezone</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {plants.map((plant) => (
                  <TableRow key={plant.id}>
                    <TableCell className="font-medium">{plant.name}</TableCell>
                    <TableCell>{plant.location || "—"}</TableCell>
                    <TableCell>{plant.timezone}</TableCell>
                    <TableCell>
                      <Badge variant={plant.is_active ? "success" : "error"}>
                        {plant.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell>{formatIST(plant.created_at, "Unknown")}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end">
                        <Button
                          size="sm"
                          variant={plant.is_active ? "danger" : "outline"}
                          disabled={updatingPlantId === plant.id}
                          isLoading={updatingPlantId === plant.id}
                          onClick={() => void handleTogglePlant(plant)}
                        >
                          {plant.is_active ? "Deactivate" : "Reactivate"}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </SectionCard>
      </div>

      {orgId ? (
        <CreatePlantModal
          tenantId={orgId}
          isOpen={createOpen}
          onClose={() => setCreateOpen(false)}
          onSuccess={(newPlant) => {
            setPlants((current) => [newPlant, ...current]);
          }}
        />
      ) : null}
    </>
  );
}
