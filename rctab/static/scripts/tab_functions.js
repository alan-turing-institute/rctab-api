"use strict";

/*ToDo*/
function openTab(evt, tabName) {
    // Show the selected tab (tabName). Set the selected tab to be the active
    // tab. The the selected tab will then be activated on page refresh.
    sessionStorage.setItem('currentTab', tabName + "_btn")

    // Get all elements with class="tabcontent" and hide them
    let tabcontent = document.getElementsByClassName("tabcontent");
    for (let i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
    }

    // Get all elements with class="tablinks" and remove the class "active"
    let tablinks = document.getElementsByClassName("tablinks");
    for (let i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }

    // Show the current tab, and add an "active" class to the button that opened the tab
    document.getElementById(tabName).style.display = "block";
    evt.currentTarget.className += " active";
}


$(document).ready( function () {
    // Get all tabs and hide them
//    let tabcontent = document.getElementsByClassName("tabcontent");
//    for (let i = 0; i < tabcontent.length; i++) {
//        tabcontent[i].style.display = "none";
//    }

    const aaBtn = document.getElementById("SubscriptionAA_btn");
    aaBtn.onclick = function(event) {openTab(event, 'SubscriptionAA')};

    const fcaBtn = document.getElementById("SubscriptionFCA_btn");
    fcaBtn.onclick = function(event) {openTab(event, 'SubscriptionFCA')};

    const uaBtn = document.getElementById("SubscriptionUA_btn");
    uaBtn.onclick = function(event) {openTab(event, 'SubscriptionUA')};

    const uBtn = document.getElementById("SubscriptionU_btn");
    uBtn.onclick = function(event) {openTab(event, 'SubscriptionU')};

    // Set the previously selected tab as active on page refresh
    if(window.location.pathname.includes('/details/')) {
        const currentTab = sessionStorage.getItem('currentTab');
        if (currentTab) {
            document.getElementById(currentTab).click();
        } else {
            document.getElementById("SubscriptionAA_btn").click();
        }
    }
} );
