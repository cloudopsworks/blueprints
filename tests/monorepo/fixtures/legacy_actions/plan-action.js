// Frozen legacy characterization fixture; extracted from cd/deploy/app/aws/action.yml before v5.11 additive changes.
const is_destroy = ((process.env.INPUTS_DESTROY || '').toLowerCase() === 'true');
const is_unlock = ((process.env.INPUTS_UNLOCK || '').toLowerCase() === 'true');
if (is_destroy) {
  core.setOutput('value', 'plan -destroy -no-color -input=false')
  console.log('destroy');
} else {
  if (is_unlock) {
    core.setOutput('value', 'force-unlock -force ' + (process.env.INPUTS_LOCK_ID || '') + '')
    console.log('unlock');
  } else {
    core.setOutput('value', 'plan -no-color -input=false')
    console.log('apply');
  }
}
