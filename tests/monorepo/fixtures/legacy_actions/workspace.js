// Frozen legacy characterization fixture; extracted from ci/config/action.yml before v5.11 additive changes.
const deployments = JSON.parse('' + (process.env.STEPS_DEPLOY_CONF_RESULT || '') + '');
const head = '' + (process.env.GITHUB_HEAD_REF || '') + '';
const base = '' + (process.env.GITHUB_BASE_REF || '') + '';
const ref = '' + (process.env.GITHUB_REF_NAME || '') + '';
var branch = base !== '' ? base : ref;

var environment = '';
var isRelease = false;
var isPreRelease = false;
var targetName = '';
var isEnabled = true;
var hasQualifier = false;
var deploymentName = '';

if ( branch.startsWith('support') ) {
  const oneMatch = deployments.support.find( ({ match }) => branch.match(new RegExp('support/'+match,'g')) );
  environment = oneMatch.env;
  targetName = oneMatch.targetName;
} else if ( branch.startsWith('release') ) {
  isPreRelease = true;
  isEnabled = (deployments.test['enabled'] == null ? true : (deployments.test['enabled'] === 'true'));
  environment = deployments.test.env;
  if ( 'targetName' in deployments.test ) {
    targetName = deployments.test.targetName;
  }
  deploymentName = `test/${environment}`;
} else if ( branch === 'develop' ) {
  isEnabled = (deployments.develop['enabled'] == null ? true : (deployments.develop['enabled'] === 'true'));
  environment = deployments.develop.env;
  if ( 'targetName' in deployments.develop ) {
    targetName = deployments.develop.targetName;
  }
  deploymentName = `develop/${environment}`;
} else {
  // This semver structure is obtained as per specification https://semver.org/ & https://regex101.com/r/vkijKf/1/
  semver = branch.match(/^v(?<major>0|[1-9]\d*)\.(?<minor>0|[1-9]\d*)\.(?<patch>0|[1-9]\d*)(?:-(?<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?/);
  if ( semver != null ) {
    const pre = semver['groups']['prerelease'];
    const buildmeta = semver['groups']['buildmetadata'];
    // buildmeta format is deploy-XXXX.yyy.zzz
    // the metasuffix should be the deploy- prefix
    if ( pre != null && buildmeta != null) {
      const metasuffix = buildmeta.match(/deploy-(?<data>.*)/);
      isEnabled = (deployments.prerelease['enabled'] == null ? true : (deployments.prerelease['enabled'] === 'true'));
      isPreRelease = true;
      hasQualifier = true;
      environment = deployments.prerelease.targets[metasuffix.groups.data].env;
      if ( 'targetName' in deployments.prerelease.targets[metasuffix.groups.data] ) {
        targetName = deployments.prerelease.targets[metasuffix.groups.data].targetName;
      }
      deploymentName = `prerelease/${metasuffix.groups.data}/${environment}`;
    } else if ( pre != null ) {
      isEnabled = (deployments.prerelease['enabled'] == null ? true : (deployments.prerelease['enabled'] === 'true'));
      // Regular expression to match following semver pattern: v1.0.2-alpha.10-uoiretu834u
      isRelease = true;
      isPreRelease = true;
      environment = deployments.prerelease.env;
      if ( 'targetName' in deployments.prerelease ) {
        targetName = deployments.prerelease.targetName;
      }
      deploymentName = `prerelease/${environment}`;
    } else if ( buildmeta != null ) {
      const metasuffix = buildmeta.match(/deploy-(?<data>.*)/);
      isRelease = true;
      hasQualifier = true;
      environment = deployments.release.targets[metasuffix.groups.data].env;
      if ( 'targetName' in deployments.release.targets[metasuffix.groups.data] ) {
        targetName = deployments.release.targets[metasuffix.groups.data].targetName;
      }
      deploymentName = `release/${metasuffix.groups.data}/${environment}`;
    } else {
      isRelease = true;
      environment = deployments.release.env;
      if ( 'targetName' in deployments.release ) {
        targetName = deployments.release.targetName;
      }
      deploymentName = `release/${environment}`;
    }
  } else if ( branch === 'master' || branch === 'main' ) {
    isRelease = true;
    environment = deployments.release.env;
    if ( 'targetName' in deployments.release ) {
      targetName = deployments.release.targetName;
    }
    deploymentName = `release/${environment}`;
  } else {
    core.setFailed('Branch not supported');
  }
}

const outputV = { 
  environment: environment, 
  isPreRelease: isPreRelease, 
  isRelease: isRelease,
  targetName: targetName,
  isEnabled: isEnabled,
  hasQualifier: hasQualifier,
  deploymentName: deploymentName
}; 
core.setOutput('workspace', environment);
core.setOutput('workspace_upper', environment.toUpperCase());
core.setOutput('isRelease', isRelease);
core.setOutput('isPreRelease', isPreRelease);
core.setOutput('targetName', targetName);
core.setOutput('isEnabled', isEnabled);
core.setOutput('hasQualifier', hasQualifier);
core.setOutput('deploymentName', deploymentName);

return outputV;
