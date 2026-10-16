// Pure, side-effect-free classifier: no account request or default creation.
const aliases = {
  takeProfit: ["takeProfit","takeProfitLong","longTakeProfitValue"],
  takeProfitShort: ["takeProfitShort","shortTakeProfitValue"],
  maximumPositions: ["maximumPositions"],
  longSlots: ["longSlots"],
  shortSlots: ["shortSlots"],
};
const allowed = new Set(Object.values(aliases).flat());
export function selectSparseBotEdit(saved, intended, userChangedKeys) {
  if (!saved || !intended || !Array.isArray(userChangedKeys) || !userChangedKeys.length) return null;
  if (!userChangedKeys.every(k => allowed.has(k))) return null;
  const patch = {};
  for (const key of userChangedKeys) {
    if (!(key in saved) || !(key in intended)) return null;
    const desired = Number(intended[key]);
    if (!Number.isFinite(desired)) return null;
    if (Number(saved[key]) !== desired) patch[key] = desired;
  }
  return Object.keys(patch).length && Object.keys(patch).length <= 5 ? patch : null;
}
