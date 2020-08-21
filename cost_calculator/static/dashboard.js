/* globals Chart:false, feather:false */

(function () {
  'use strict'

  feather.replace()

  const namespace = document.getElementsByClassName('namespace-option')[1].value;
  const costURL = `/api/cost/pods/${namespace}`;
  console.log(costURL);
  fetch(costURL)
    .then(resp => resp.json())
    .then(data => {
      console.log(data)
      // Graphs
      var ctx = document.getElementById('forcast-chart').getContext('2d');
      // eslint-disable-next-line no-unused-vars
      var myChart = new Chart(ctx, {
        "type": 'line',
        "data": {
          labels: [
            'Sunday',
            'Monday',
            'Tuesday',
            'Wednesday',
            'Thursday',
            'Friday',
            'Saturday'
          ],
          datasets: [{
            data: data.costs,
            lineTension: 0,
            backgroundColor: 'transparent',
            borderColor: '#007bff',
            borderWidth: 4,
            pointBackgroundColor: '#007bff'
          }]
        },
        options: {
          responsive: true,
          scales: {
            yAxes: [{
              ticks: {
                beginAtZero: false
              }
            }]
          },
          layout: {
            padding: {
              left: 50,
              right: 0,
              top: 0,
              bottom: 0
          },
          legend: {
            display: true
          }
        }
      }}); 
    });
}())
