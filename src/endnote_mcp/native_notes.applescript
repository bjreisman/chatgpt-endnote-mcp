-- Fixed read-only helper. The configured path is an argument, never source code.
on run argv
    if (count of argv) is not 1 then error "LIBRARY_PATH_REQUIRED"
    if not (application id "com.ThomsonResearchSoft.EndNote" is running) then error "ENDNOTE_NOT_RUNNING"
    tell application id "com.ThomsonResearchSoft.EndNote"
        if (count of documents) is not 1 then error "ONE_LIBRARY_REQUIRED"
        set libraryDocument to item 1 of documents
        set libraryFile to file of libraryDocument
        if (POSIX path of libraryFile) is not (item 1 of argv) then error "WRONG_LIBRARY"
        set recordIDs to retrieve "all" records in libraryDocument
        return export recordIDs as "RSXML"
    end tell
end run
