function toErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "string" && error) {
    return error;
  }
  return fallback;
}

export interface MachinesInitialLoadResult {
  fatalError: string | null;
  summaryPromise: Promise<unknown>;
}

export async function loadMachinesInitialChannels({
  loadFleet,
  loadSummary,
  fallbackError = "Failed to fetch machines",
}: {
  loadFleet: () => Promise<unknown>;
  loadSummary: () => Promise<unknown>;
  fallbackError?: string;
}): Promise<MachinesInitialLoadResult> {
  const summaryPromise = Promise.resolve()
    .then(loadSummary)
    .catch(() => undefined);

  try {
    await loadFleet();
    return {
      fatalError: null,
      summaryPromise,
    };
  } catch (error) {
    return {
      fatalError: toErrorMessage(error, fallbackError),
      summaryPromise,
    };
  }
}
