<%inherit file="base.mak"/>

<h2>Run ${run['_id']}
  <form action="/tests/stop" method="POST" style="display:inline">
    <input type="hidden" name="run-id" value="${run['_id']}">
    <button type="submit" class="btn btn-danger">
      Stop
    </button>
  </form>
</h2>

<form class="form-inline" action="/tests/run_more" method="POST">
  <label class="control-label">Adjust number of games:</label>
  <input name="num-games" value="${run['args']['num_games']}">
  <input type="hidden" name="run" value="${run['_id']}" />
  <button type="submit" class="btn btn-primary">Submit</button>
</form>

<%include file="elo_results.mak" args="run=run" />

%for arg, v in sorted(run['args'].iteritems()):
  <div>
    <b>${arg}</b>: ${v}
  </div>
%endfor

<h3>Tasks</h3>
<table class='table table-striped table-condensed'>
 <thead>
  <tr>
   <th>Idx</th>
   <th>Started</td>
   <th>Pending</th>
   <th>Worker</th>
   <th>Last Updated</th>
   <th>Games</th>
   <th>Played</th>
   <th>Wins</th>
   <th>Losses</th>
   <th>Draws</th>
  </tr>
 </thead>
 <tbody>
  %for idx, task in enumerate(run['tasks']):
  <tr>
   <%
     stats = task.get('stats', {})
     if 'stats' in task:
       total = stats['wins'] + stats['losses'] + stats['draws']
     else:
       total = '0'

     if 'worker_info' in task:
       machine_info = task['worker_info'].get('username', '') + '-' + str(task['worker_info']['concurrency']) + 'cores'
     else:
       machine_info = '-'
   %>
   <td>${idx}</td>
   <td>${task['active']}</td>
   <td>${task['pending']}</td>
   <td>${machine_info}</td>
   <td>${task.get('last_updated', '-')}</td>
   <td>${task['num_games']}</td>
   <td>${total}</td>
   <td>${stats.get('wins', '-')}</td>
   <td>${stats.get('losses', '-')}</td>
   <td>${stats.get('draws', '-')}</td>
  </tr>
  %endfor
 </tbody>
</table>
