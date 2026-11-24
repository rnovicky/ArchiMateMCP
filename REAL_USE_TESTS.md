# Testing the MCP server in real use

A sequence of prompts to try the ArchiMate MCP server in Claude (Desktop or
Code) on your own models, and to report what you find. It complements the
automated tests: they check that the tools do what they say; this checks
whether an assistant, given real questions, finds the right tools, uses them
well and answers usefully.

Each step gives a **prompt** to paste (adapt the names in `<…>` to your
model), the **tools** it should lead to, **what good looks like**, and
**what to note**. About 45 minutes for everything; parts A and B (reading)
and part C (writing) can be done on different days.

## Before you start

1. **Versions:** the API 3.19.0 and the MCP server 1.12.0 (or newer) are
   installed and running; `api_status` (step A1) shows them. Steps A to C12
   were run on 2026-10-25 with the API 3.11.0 and the MCP server 1.7.0
   (see *Findings so far*).
2. **A model to write into.** Do the writing steps (part C) on a model you
   can lose:
   * with a key that may create models (role `admin`): step C1 creates one;
   * otherwise import a copy of a model (the Browser's *Import model…* with
     *as a separate copy*, or `archimateapi.bat import model.xml new`), and
     use its name in part C.
3. **Writing on**, for part C: `ALLOW_WRITE=true` and an `editor` (or
   `admin`) key in the MCP's `.env` (see [ACCESS_RIGHTS.md](ACCESS_RIGHTS.md)).
4. **Start each part in a new conversation**, so that earlier answers do not
   help the assistant.

## What to send back

For each step, one line is enough: **OK**, or what went wrong, for example
*"asked which model although only one was meant"*, *"used search 6 times
instead of get_element"*, *"answer missed the relationships to X"*, *"too
slow"*, *"wrong element type chosen"*. Also useful:

* the conversation itself, exported or copied, for the steps that went
  wrong (keep names out that must not leave your organisation);
* `changes.log` from the MCP server's folder after part C;
* anything you missed: a question you wanted to ask that no tool answers.

---

## Findings so far

| Date | Step | Finding | Done |
| --- | --- | --- | --- |
| 2026-10-25 | C7b | Chose the folder for a deleted folder's contents itself | 1.6.0: the tool and its refusal say to ask the user |
| 2026-10-25 | C8 | Deleted the Customer with its relationships without asking | 1.6.0: the refusal says to tell the user and ask before `cascade=true`; the server's instructions say to ask before every delete |

## A. Finding one's way

| # | Prompt | Tools expected | Good looks like | Note |
| --- | --- | --- | --- | --- |
| A1 | *Which ArchiMate server are you connected to, and may you write?* | `api_status` | The versions of the API and the MCP server, the key's name and role, `writing` true or false | Whether the role is what you set |
| A2 | *Which models are there? Give me an overview of `<model>`.* | `list_models`, `model_overview` | Sizes, the layers and types it holds, the top folders, the properties in use | Whether the overview is the right length |
| A3 | *Find `<an application you know>`.* | `search`, maybe `get_element` | The element, with its type and where it is filed | Did it find it at once? With a partial or misspelt name? |
| A4 | *Tell me everything about `<that application>`: what it serves, what it runs on, who owns it.* | `get_element` (relationships, properties, views) | Relationships in both directions, by type, with the other ends' names; properties; views that show it | Anything missing or wrong |
| A5 | *Find `<a name several elements share, e.g. a process name used twice>`.* | `search`, then a question back | It lists the candidates and asks which one, or chooses sensibly and says so | Whether it guessed silently |
| A6 | *Which views show `<that application>`? Describe the first one.* | `list_views`, `get_view` | The views; for one: its elements, how they are nested, its relationships | Whether the description matches what you see in Archi or the Browser |
| A7 | *What is in the folder `<a folder>`, and its sub-folders?* | `browse_folders` | Sub-folders with counts, then what is filed there | Paths written as you know them |
| A8 | *Open that in the ArchiMate Browser.* | `browser_link` | A link that opens the right diagram | Click it: does the Browser show the same? |
| A9 | *Write a short report on `<an application>` as a Word document (or Markdown), with the diagram of its neighbourhood and of the view `<a view>`.* | `neighbourhood`, `diagram_image` (with the link, and with the view), then the document | The document with both pictures in it; the files in the MCP server's `images` folder | Do the pictures match the Browser's? How long did the first and the next image take? (1.12.0) |

## B. Questions about the architecture

| # | Prompt | Tools expected | Good looks like | Note |
| --- | --- | --- | --- | --- |
| B1 | *What would be affected if `<a technology node or system software>` went down?* | `impact_analysis` | Affected elements level by level, each with how it is reached; a summary by layer | Plausible? Something missing or too much? |
| B2 | *What does `<a business process>` depend on, down to the infrastructure?* | `impact_analysis` (dependencies) | The chain of applications and technology below it | Whether the direction was understood |
| B3 | *How are `<element X>` and `<element Y>` connected?* | `find_paths` | One or more paths as readable chains | The shortest paths you would expect |
| B4 | *Show me the neighbourhood of `<element>`, two steps out, only application and technology.* | `neighbourhood` (with filters) | Elements with their distance, relationships among them, a Browser link | Filters applied? |
| B5 | *Which application components serve which business processes?* | `relationship_matrix` | A matrix, or the list of pairs, with the paths | Compare with what you know |
| B6 | *Draw a landscape of the capabilities with the applications that realize them.* | `landscape` | A tree of capabilities with the applications below them | Structure right? Property colours if asked |
| B7 | *Review the quality of `<model>`. What should be fixed first?* | `model_quality`, maybe `model_overview` | Findings by importance with examples and ids, suggestions | Useful, or noise? |
| B8 | *Which relationship can I use from a Node to an Application Component? And from a Business Actor to a Goal?* | `allowed_relationships` | The allowed types, with a short explanation of the usual choice | Matches Archi's magic connector? |

## C. Changing a model

Use the model you can lose (see *Before you start*). In the prompts it is
`<test model>`.

| # | Prompt | Tools expected | Good looks like | Note |
| --- | --- | --- | --- | --- |
| C1 | *Create a new empty model called "MCP test `<date>`".* (only with an admin key) | `create_model` | The model, with Archi's top folders | Without an admin key: does it explain why it cannot? |
| C2 | *In `<test model>`, model a small order process: a Customer (business actor), an Order Handling process, a Web Shop application serving it, and the Order data object it accesses. Use the right relationships.* | `search` (to avoid duplicates), `allowed_relationships`, `apply_changes` | **One** `apply_changes` call creating 4 elements and 3 relationships, filed in Business, Application, Relations; the answer lists them with ids | Number of calls; types and relationships right? |
| C3 | *Add a property "owner" = "Sales" to all three business elements, and "lifecycle" = "current" to the Web Shop.* | `apply_changes` (setProperty) | One call | — |
| C4 | *Rename every relationship of the order process that has no name, with a short verb phrase.* | `get_element` / `get_view`, then `apply_changes` (updateRelationship) | One `apply_changes` call with all renames | The real-use case of before: now one call? |
| C5 | *Create a Composition from the Customer to the Order Handling process.* | `create_relationship` or `apply_changes`, refused | The refusal explained, with the allowed types (from the API's rules) and a better suggestion | Whether it insisted or understood |
| C6 | *Create the Web Shop again.* | `search` first, or a duplicate warning | It notices the Web Shop exists, and asks or refuses | — |
| C7 | *Move the Order data object into a new sub-folder "Data" of Application.* | `create_folder`, `file_item` | Two calls: the folder, then the filing | Did it look first whether "Data" exists? |
| C7b | *Rename the folder "Data" to "Data objects", then delete it.* | `update_folder`, `delete_folder` (refused while not empty), then a question | It renames it; for the delete it says the folder is not empty and asks where the Order data object should go (`move_contents_to`) | Did it ask, or choose a folder itself? |
| C8 | *Delete the Customer.* | `delete_element`, refused without cascade, then a question | It says what would go with it (relationships, views) and asks before `cascade=true` | Did it ask, or just do it? Did Claude ask your permission for the delete? |
| C9 | *Change the Web Shop into an Application Service.* | `update_element`, maybe refused | Refused if its relationships would not be allowed any more, with an explanation | — |
| C10 | *Undo what you did in C3.* | `apply_changes` (removeProperty) | It removes exactly those properties (there is no undo tool; it should know what it did) | Whether it remembers or reads `changes.log`-like answers |
| C12 | *Give the test model a property "status" = "draft", rename the property "owner" to "responsible", then delete "lifecycle".* | `set_property` (`kind=model`), `update_property_definition`, `delete_property_definition` (refused while it has values, then a question) | It asks before deleting the values | — |
| C13 | *Who changed the Web Shop, and what did you change today in `<test model>`?* | `model_history` (item, then user and since) | The changes with time, user and client, before and after | Does it tell your changes from the Browser's? |
| C14 | *Show me the Web Shop.* Then rename it yourself elsewhere (the API's /docs, or a second chat), then: *Add "Handles all online orders" as its documentation.* (1.8.0, API 3.12.0) | `get_element` (its `version`), then `update_element` with `expected_version` | Refused: it says you (or the other client) renamed it, from what to what, changes nothing, and asks before trying again | Does it ask, or write anyway? |
| C11 | Open `<test model>` in the ArchiMate Browser | – | The elements, relationships, folders and properties as created | Anything odd in the Browser |

## D. Limits and errors

| # | Prompt | Good looks like | Note |
| --- | --- | --- | --- |
| D1 | *In `<a linked model>`, rename `<element>`.* (if you have a linked model) | Refused: the model is read-only, updated from its file | Explained clearly? |
| D2 | Stop the API, then: *Find `<element>`.* | It says the API cannot be reached and how to fix it | — |
| D3 | *Give me all elements of `<a big type>` with their documentation.* | Lists stop at the limit and say so ("truncated", the total); it offers to narrow down | Answer size acceptable? |

## E. Overall impression

A few sentences: what was most useful, what felt slow or clumsy, what you
would ask next that no tool answers, and whether the answers were the right
length.
