'use strict';
(function () {
  // Calculate base path for assets based on current page location
  function getBasePath() {
    var pathname = window.location.pathname;
    
    // Find the base directory by looking for common patterns
    var baseDir = '';
    if (pathname.includes('/dist/')) {
      // Extract everything after /dist/
      var distIndex = pathname.indexOf('/dist/');
      var afterDist = pathname.substring(distIndex + 6); // +6 to skip '/dist/'
      baseDir = afterDist;
    } else {
      // Fallback for other deployment scenarios
      var pathSegments = pathname.split('/').filter(segment => segment.length > 0);
      if (pathSegments.length > 0) {
        // Remove the last segment (filename) and any empty segments
        var lastSegment = pathSegments[pathSegments.length - 1];
        if (lastSegment.includes('.html')) {
          pathSegments.pop(); // Remove filename
        }
        baseDir = pathSegments.join('/');
      }
    }
    
    // Calculate depth based on directory structure within the dist folder
    if (!baseDir || baseDir === '' || baseDir === 'index.html') {
      return ''; // Root level
    }
    
    var segments = baseDir.split('/').filter(segment => segment.length > 0 && !segment.includes('.html'));
    return '../'.repeat(segments.length);
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelector('#btn-default').addEventListener('click', function () {
      notifier.show('Hello!', 'I am a default notification.', '', '', 0);
    });

    document.querySelector('#btn-info').addEventListener('click', function () {
      notifier.show('Reminder!', 'You have a meeting at 10:30 AM.', 'info', '', 0);
    });

    document.querySelector('#btn-success').addEventListener('click', function () {
      notifier.show('Well Done!', 'You just submit your resume successfully.', 'success', '', 0);
    });

    document.querySelector('#btn-warning').addEventListener('click', function () {
      notifier.show('Warning!', 'The data presented here can be change.', 'warning', '', 0);
    });

    document.querySelector('#btn-danger').addEventListener('click', function () {
      notifier.show('Sorry!', 'Could not complete your transaction.', 'danger', '', 0);
    });

    document.querySelector('#btn-default-i').addEventListener('click', function () {
      notifier.show('Default!', 'I am a default notification.', '', getBasePath() + 'assets/images/notification/clock-48.png', 0);
    });

    document.querySelector('#btn-info-i').addEventListener('click', function () {
      notifier.show('Reminder!', 'You have a meeting at 10:30 AM.', 'info', getBasePath() + 'assets/images/notification/survey-48.png', 0);
    });

    document.querySelector('#btn-success-i').addEventListener('click', function () {
      notifier.show('Well Done!', 'You just submit your resume successfully.', 'success', getBasePath() + 'assets/images/notification/ok-48.png', 0);
    });

    document.querySelector('#btn-warning-i').addEventListener('click', function () {
      notifier.show(
        'Warning!',
        'The data presented here can be change.',
        'warning',
        getBasePath() + 'assets/images/notification/medium_priority-48.png',
        0
      );
    });

    document.querySelector('#btn-danger-i').addEventListener('click', function () {
      notifier.show('Sorry!', 'Could not complete your transaction.', 'danger', getBasePath() + 'assets/images/notification/high_priority-48.png', 0);
    });

    document.querySelector('#btn-default-ac').addEventListener('click', function () {
      notifier.show('Default!', 'I am a default notification.', '', getBasePath() + 'assets/images/notification/clock-48.png', 4000);
    });

    document.querySelector('#btn-info-ac').addEventListener('click', function () {
      notifier.show('Reminder!', 'You have a meeting at 10:30 AM.', 'info', getBasePath() + 'assets/images/notification/survey-48.png', 4000);
    });

    document.querySelector('#btn-success-ac').addEventListener('click', function () {
      notifier.show('Well Done!', 'You just submit your resume successfully.', 'success', getBasePath() + 'assets/images/notification/ok-48.png', 4000);
    });

    document.querySelector('#btn-warning-ac').addEventListener('click', function () {
      notifier.show(
        'Warning!',
        'The data presented here can be change.',
        'warning',
        getBasePath() + 'assets/images/notification/medium_priority-48.png',
        4000
      );
    });

    document.querySelector('#btn-danger-ac').addEventListener('click', function () {
      notifier.show('Sorry!', 'Could not complete your transaction.', 'danger', getBasePath() + 'assets/images/notification/high_priority-48.png', 4000);
    });

    var notificationId;
    var showNotification = function () {
      notificationId = notifier.show(
        'Reminder!',
        'You have a meeting at 10:30 AM.',
        'info',
        getBasePath() + 'assets/images/notification/survey-48.png',
        4000
      );
    };

    var hideNotification = function () {
      notifier.hide(notificationId);
    };

    document.querySelector('#btn-nt-show').addEventListener('click', showNotification);

    document.querySelector('#btn-nt-hide').addEventListener('click', hideNotification);
  });
})();
