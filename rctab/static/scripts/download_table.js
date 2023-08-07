function download_table_as_csv(table_id, start_date, separator = ',') {
    // see https://stackoverflow.com/questions/15547198/export-html-table-to-csv-using-vanilla-javascript
    // Select rows from table_id
    var rows = document.querySelectorAll('table#' + table_id + ' tr');
    var fulltable = document.getElementById("fullusagetable")
    fulltable.style.display = "block"
    // Construct csv
    var csv = [];
    for (var i = 0; i < rows.length; i++) {
        var row = [], cols = rows[i].querySelectorAll('td, th');
        for (var j = 0; j < cols.length; j++) {
            // Clean innertext to remove multiple spaces and jumpline (break csv)
            var data = cols[j].innerText.replace(/(\r\n|\n|\r)/gm, '').replace(/(\s\s)/gm, ' ')
            // Escape double-quote with double-double-quote
            data = data.replace(/"/g, '""');
            // Push escaped string
            row.push('"' + data + '"');
        }
        csv.push(row.join(separator));
    }
    var csv_string = csv.join('\n');
    // Download it
    var filename = table_id + '_' + new Date().toLocaleDateString().replace(/\//g, '-') + '_' + start_date + '.csv';
    var link = document.createElement('a');
    link.style.display = 'none';
    link.setAttribute('target', '_blank');
    link.setAttribute('href', 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv_string));
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    fulltable.style.display = "none"
}
