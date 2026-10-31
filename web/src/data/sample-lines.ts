// Written by scripts/export_web_samples.py; do not edit. Each sample's lines are a chunk
// of their own, which the console fetches only when someone picks that sample.
const sampleLines = new Map<string, () => Promise<{ default: { lines: string[] } }>>([
  ["linux.auth_failures", () => import("./samples/linux.auth_failures.json")],
  ["openssh.bruteforce", () => import("./samples/openssh.bruteforce.json")],
  ["mac.cocoa_scripting_noise", () => import("./samples/mac.cocoa_scripting_noise.json")],
  ["android.permission_noise", () => import("./samples/android.permission_noise.json")],
  ["apache.mod_jk_worker_error", () => import("./samples/apache.mod_jk_worker_error.json")],
  ["openstack.image_cache_missing", () => import("./samples/openstack.image_cache_missing.json")],
  ["proxifier.proxy_connectivity", () => import("./samples/proxifier.proxy_connectivity.json")],
  ["hdfs.block_serve_exceptions", () => import("./samples/hdfs.block_serve_exceptions.json")],
  ["hadoop.resourcemanager_unreachable", () => import("./samples/hadoop.resourcemanager_unreachable.json")],
  ["hadoop.hdfs_lease_renewal", () => import("./samples/hadoop.hdfs_lease_renewal.json")],
  ["zookeeper.quorum_connection_loss", () => import("./samples/zookeeper.quorum_connection_loss.json")],
  ["zookeeper.old_client_noise", () => import("./samples/zookeeper.old_client_noise.json")],
  ["bgl.kernel_panic", () => import("./samples/bgl.kernel_panic.json")],
  ["bgl.memory_interrupts", () => import("./samples/bgl.memory_interrupts.json")],
  ["bgl.lustre_mount_failure", () => import("./samples/bgl.lustre_mount_failure.json")],
  ["bgl.ciod_link_failure", () => import("./samples/bgl.ciod_link_failure.json")],
  ["bgl.tree_network_errors", () => import("./samples/bgl.tree_network_errors.json")],
  ["hpc.interconnect_link_errors", () => import("./samples/hpc.interconnect_link_errors.json")],
  ["hpc.component_unavailable", () => import("./samples/hpc.component_unavailable.json")],
  ["hpc.psu_failure", () => import("./samples/hpc.psu_failure.json")],
]);

export default sampleLines;
