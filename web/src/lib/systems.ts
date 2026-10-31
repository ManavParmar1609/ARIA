// Display names for the log systems ARIA knows (mirrors SYSTEM_NAMES in the report composer).
export const SYSTEM_NAMES: Record<string, string> = {
  // Logs whose format was not named ("Not sure" on New triage).
  generic: "Unknown system",
  android: "Android",
  apache: "Apache",
  bgl: "BlueGene/L",
  hadoop: "Hadoop",
  hdfs: "HDFS",
  healthapp: "HealthApp",
  hpc: "HPC",
  linux: "Linux",
  mac: "macOS",
  openssh: "OpenSSH",
  openstack: "OpenStack",
  proxifier: "Proxifier",
  spark: "Spark",
  thunderbird: "Thunderbird",
  windows: "Windows",
  zookeeper: "ZooKeeper",
};

export const systemName = (system: string | null | undefined): string =>
  system ? (SYSTEM_NAMES[system] ?? system) : "";

const TRIGGERS: Record<string, string> = {
  api: "from the API",
  manual: "started in the console",
  alertmanager: "from an Alertmanager alert",
  grafana: "from a Grafana alert",
  webhook: "from a webhook alert",
  agui: "from an AG-UI client",
  a2a: "delegated by another agent",
  cli: "from the command line",
  eval: "from an evaluation",
  demo: "a recorded demo",
  scan: "from a log scan",
  fork: "copied from another incident",
  replay: "a real incident, replayed",
  sample: "a sample, built from real lines",
};

export const triggerLabel = (trigger: string | null | undefined): string =>
  trigger ? (TRIGGERS[trigger] ?? `from ${trigger}`) : "";
