function openTab(evt, tabName) {
    // Show the selected tab (tabName). Set the selected tab to be the active
    // tab. The the selected tab will then be activated on page refresh.
    sessionStorage.setItem('currentTab', tabName + "_btn")

    // Declare all variables
    var i, tabcontent, tablinks;

    // Get all elements with class="tabcontent" and hide them
    tabcontent = document.getElementsByClassName("tabcontent");
    for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
    }

    // Get all elements with class="tablinks" and remove the class "active"
    tablinks = document.getElementsByClassName("tablinks");
    for (i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }

    // Show the current tab, and add an "active" class to the button that opened the tab
    document.getElementById(tabName).style.display = "block";
    evt.currentTarget.className += " active";
}


$(document).ready( function () {
    // Set the previously selected tab as active on page refresh if exists
    if(window.location.pathname.includes('/details/')) {
        const currentTab = sessionStorage.getItem('currentTab');
        if (currentTab) {
            document.getElementById(currentTab).click();
        } else {
            document.getElementById("SubscriptionAA_btn").click();
        }
    }
} );
