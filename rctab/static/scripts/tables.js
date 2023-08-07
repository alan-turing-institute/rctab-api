$(document).ready( function () {
    // Only run on the main page
    if ($('#subscription_table_all').length > 0) {
        $('#subscription_table_all').DataTable({
            columnDefs: [
                { orderable: false, targets: 0 }
            ],
            order: [[2, 'asc']],
            paging: false,
        });
        // Hide abolished rows by default
        hideAbolishedRows(true);
        document.getElementById("show_abolished_checkbox").checked = false;
    }
} );

function hideAbolishedRows(input) {
  // Hide or show abolished rows by finding rows with the red x and turning
  // them off or on.
  // Loop through each row and get the value of the 1st column
  // If the value is a red x and the checkbox is ticked, hide the row by setting
  // the display to None, else, show it by resetting the display property to its
  // default by setting it to ''.
  const check = input.checked
  const rows = document.querySelectorAll('#subscription_table_all > tbody > tr')
  rows.forEach(row => {
      const dataField = row.querySelectorAll('td')[0]
      if(dataField.firstElementChild.firstChild.tagName != "IMG") {
          row.style.display = check ? '': 'none'
      }
  })
}
