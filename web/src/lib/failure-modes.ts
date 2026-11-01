// Failure modes as people write them; the rest read fine with spaces for underscores.
const FAILURE_NAMES: Record<string, string> = {
  auth_failures: "authentication failures",
  bruteforce: "brute-force attempts",
  ciod_link_failure: "CIOD link failure",
  cocoa_scripting_noise: "Cocoa scripting noise",
  hdfs_lease_renewal: "HDFS lease renewal",
  lustre_mount_failure: "Lustre mount failure",
  mod_jk_worker_error: "mod_jk worker errors",
  psu_failure: "PSU failure",
  resourcemanager_unreachable: "ResourceManager unreachable",
  unfinished_work: "work that stops partway",
};

/** A failure mode in words: "bruteforce" reads "brute-force attempts". */
export function failureName(mode: string): string {
  return FAILURE_NAMES[mode] ?? mode.replaceAll("_", " ");
}
