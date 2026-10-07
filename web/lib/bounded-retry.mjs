export async function withBoundedRetry(operation, options = {}) {
  const attempts = Math.max(1, Number(options.attempts || 2));
  const delays = Array.isArray(options.delays) ? options.delays : [300];
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try { return await operation(attempt); }
    catch (error) {
      lastError = error;
      if (attempt + 1 >= attempts) break;
      const delay = Math.max(0, Number(delays[Math.min(attempt, delays.length - 1)] || 0));
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  throw lastError;
}
