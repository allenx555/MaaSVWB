import type { FullConfig } from '@nekosu/maa-tools'

const config: FullConfig = {
  cwd: import.meta.dirname,
  // Keep in sync with tools/project_versions.json and requirements.txt.
  maaVersion: '5.12.3',
  interfacePath: 'assets/interface.json',
  check: {
    override: {
      // 忽略 mpe-config 带来的报错
      // ignore warning caused by mpe-config
      // 'mpe-config': 'ignore'
    }
  }
}

export default config
