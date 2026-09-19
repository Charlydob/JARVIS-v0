param(
  [switch]$Write,
  [string]$BaseUrl = $(if ($env:JARVIS_BOOKSHELL_API_URL) { $env:JARVIS_BOOKSHELL_API_URL } else { "https://api-bookshell.charlydob.com" })
)

$ErrorActionPreference = "Stop"
$token = $env:JARVIS_BOOKSHELL_API_TOKEN
if (-not $token) { throw "JARVIS_BOOKSHELL_API_TOKEN is required" }
$headers = @{ Authorization = "Bearer $token"; "Cache-Control" = "no-cache" }
$timings = @()

function Invoke-ContractRequest {
  param([string]$Method, [string]$Path, $Body = $null, [hashtable]$ExtraHeaders = @{})
  $allHeaders = $headers.Clone()
  foreach ($key in $ExtraHeaders.Keys) { $allHeaders[$key] = $ExtraHeaders[$key] }
  $params = @{ Method = $Method; Uri = "$BaseUrl$Path"; Headers = $allHeaders }
  if ($null -ne $Body) { $params.ContentType = "application/json"; $params.Body = ($Body | ConvertTo-Json -Depth 20 -Compress) }
  $watch = [Diagnostics.Stopwatch]::StartNew()
  $response = Invoke-WebRequest @params
  $result = $response.Content | ConvertFrom-Json -AsHashtable
  $watch.Stop()
  $script:timings += [pscustomobject]@{ Method = $Method; Path = $Path; Milliseconds = $watch.ElapsedMilliseconds }
  return $result
}

$capabilities = Invoke-ContractRequest GET "/jarvis/capabilities"
if (-not $capabilities.ok) { throw "Capabilities failed" }
$book = Invoke-ContractRequest GET "/jarvis/books?mode=current&title=Musashi"
$gym = Invoke-ContractRequest GET "/jarvis/data/gym/gym"
$habits = Invoke-ContractRequest GET "/jarvis/data/habits"
$finance = Invoke-ContractRequest GET "/jarvis/data/finance/finance"
$guardias = Invoke-ContractRequest GET "/jarvis/reminders?eventType=guardia&subject=Laura&limit=100"

if ($Write) {
  if (-not $book.found) { throw "Musashi not found" }
  $originalPage = [int]$book.book.currentPage
  try {
    $null = Invoke-ContractRequest PATCH "/jarvis/books/progress" @{ title = "Musashi"; page = 221 }
    $to222 = Invoke-ContractRequest PATCH "/jarvis/books/progress" @{ title = "Musashi"; page = 222 }
    $verify222 = Invoke-ContractRequest GET "/jarvis/books?mode=current&title=Musashi"
    if (-not $to222.verified -or [int]$verify222.book.currentPage -ne 222) { throw "Book progress verification failed" }
  } finally {
    $null = Invoke-ContractRequest PATCH "/jarvis/books/progress" @{ title = "Musashi"; page = $originalPage }
  }

  $today = (Get-Date).ToString("yyyy-MM-dd")
  $idem = "jarvis-contract-$([guid]::NewGuid())"
  $created = Invoke-ContractRequest POST "/jarvis/reminders" @{
    title = "JARVIS contract fixture"; targetDate = $today; targetTime = "23:58"; timezone = "Europe/Zurich"
    status = "pending"; source = @{ type = "manual"; metadata = @{ createdBy = "jarvis-contract" } }
  } @{ "Idempotency-Key" = $idem }
  $reminderId = $created.reminder.id
  try {
    $todayRows = Invoke-ContractRequest GET "/jarvis/reminders?range=today&limit=100"
    $weekRows = Invoke-ContractRequest GET "/jarvis/reminders?range=this_week&limit=100"
    $searchRows = Invoke-ContractRequest GET "/jarvis/reminders?q=JARVIS%20contract%20fixture&limit=100"
    if ($reminderId -notin @($todayRows.reminders.id) -or $reminderId -notin @($weekRows.reminders.id) -or $reminderId -notin @($searchRows.reminders.id)) { throw "Reminder read-back failed" }
    $null = Invoke-ContractRequest PATCH "/jarvis/reminders/$reminderId" @{ targetTime = "23:57" }
    $changed = Invoke-ContractRequest GET "/jarvis/reminders/$reminderId"
    if ($changed.reminder.targetTime -ne "23:57") { throw "Reminder update failed" }
  } finally {
    $null = Invoke-ContractRequest DELETE "/jarvis/reminders/$reminderId"
    $cancelled = Invoke-ContractRequest GET "/jarvis/reminders/$reminderId"
    if ($cancelled.reminder.status -ne "cancelled") { throw "Reminder cancellation failed" }
  }

  $noteId = "jarvis_contract_$([guid]::NewGuid().ToString('N'))"
  try {
    $null = Invoke-ContractRequest PUT "/jarvis/data/notes/notes/$noteId" @{ title = "Contract fixture"; content = "created"; createdAt = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() }
    $null = Invoke-ContractRequest PATCH "/jarvis/data/notes/notes/$noteId" @{ content = "updated" }
    $notes = Invoke-ContractRequest GET "/jarvis/data/notes/notes"
    if ($notes.data.$noteId.content -ne "updated") { throw "Note verification failed" }
  } finally {
    $null = Invoke-ContractRequest DELETE "/jarvis/data/notes/notes/$noteId"
  }
}

[pscustomobject]@{
  ok = $true
  writeMode = [bool]$Write
  guardiasLaura = @($guardias.reminders).Count
  gymAvailable = ($null -ne $gym.data)
  habitsAvailable = ($null -ne $habits.data)
  financeAvailable = ($null -ne $finance.data)
  timings = $timings
} | ConvertTo-Json -Depth 5
