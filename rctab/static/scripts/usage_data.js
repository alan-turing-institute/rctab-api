"use strict";

async function fetchUsageData(event) {
    const usageSubmitBtn = document.getElementById("usagesubmitbtn")
    usageSubmitBtn.disabled=true;

    const outDiv = document.getElementById("azureusageinfo")
    const datestring = document.getElementById("timeperiodstr").value
    const subscription_id = document.getElementById("subscription_id").innerText
    outDiv.innerHTML = '<div class="search-overlay"><div class="loader"></div><div class="loader-text"><br><br>Loading data<br><br>This may take a few seconds or a few minutes depending on the length of time requested.</div></div>'
    event.preventDefault();
    await fetch("/process_usage/" + subscription_id + "?timeperiodstr=" + datestring, {
        method: "GET",
    })
    .then(response => {
        return response.text();
    })
    .then(html => {
        $("#azureusageinfo").html(html)
    })
    usageSubmitBtn.disabled=false;
}

$(document).ready(function () {
    const usageSubmitBtn = document.getElementById("usagesubmitbtn");
    usageSubmitBtn.onclick = fetchUsageData;
} );
