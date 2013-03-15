#!/usr/bin/python

# For tasks
sys.path.append(os.path.expanduser('~/fishtest/fishtest'))
from fishtest.rundb import RunDb

def scavenge_tasks(scavenge=True, minutes=20):
  """Check for tasks that have not been updated recently"""
  rundb = RunDb()
  for run in rundb.get_runs():
    changed = False
    for task in run['tasks']:
      if task['active'] and task['last_updated'] < datetime.utcnow() - timedelta(minutes=minutes):
        print 'Scavenging', task
        task['active'] = False 
        changed = True
    if changed and scavenge:
      rundb.runs.save(run)

def main():
  scavenge_tasks(scavenge=False)

if __name__ == '__main__':
  main()