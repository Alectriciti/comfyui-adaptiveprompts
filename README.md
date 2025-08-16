# Adaptive Prompts


- **August 15, 2025** Established a somewhat working version of these nodes. Currently, while it may not as fleshed out as dynamic-prompts, it exceeds it in other ways by providing the essentials and adding new capabilities. But it seems to be a suitable replacement now.

## Introduction

> Adaptive Prompts is a modern reimagining of dynamic prompts for ComfyUI. It lets you randomize, restructure, and clean up prompts with powerful wildcard and string tools. For the sake of consistency, I will still refer to them as Dynamic Prompts.

Inspired by the legendary [dynamic-prompts](https://github.com/adieyal/dynamicprompts) by adieyal, which has served as the bread and butter of prompt building for years. Unfortunately, it hasn't been updated in years now.

<img src="images/example-1.png"/>


# ⚡ Quick Node Reference 

| Node | Purpose | Notes |
|------|---------|-------|
| 🎨 Prompt Generator | Core dynamic prompt node | Formerly known as "Random Prompts" |
| 📦 Prompt Rewrap | Inverse natural words into respective wildcards | New |
| 🔁 Prompt Replace | Search & Replace with wildcards | New |
| ♻️ Shuffle Tags | Randomize tag ordering | New |
| 🟰 Normalize Lora Tags | Provides lora weight control | New |
| 📃 String Merger | Combines multiple strings into one | New|
| 🧹 Cleanup Tags | Multi-tool: Can tidy up prompts, such as removing whitespace, extra commas, lora tags, etc | New |


# Dynamic Prompting Quickstart Guide
> *(This does not include new features, so feel free to skip this section if you're already familiar with how dynamic-prompts works.)*
<details>
  <summary><b>Quickstart Guide</b></summary>
  
  
### 💡 Basic Example
There are two primary methods to randomize a prompt:

1. **Brackets:** ```{red|green|blue}``` randomly chooses between "red", "green", and "blue"
2. **Wildcards:** ```__fruit__``` chooses a random line from a .txt file called "fruit.txt"

**/wildcards/fruit.txt Example:**
```
# comments can be applied like this
apple
orange
banana

# brackets work here too, effectively making the options less common
{strawberry|blueberry}

# the more options you add, the less likely you'll roll that option
{kiwi|mango|pineapple|pomegranate}

# wildcards can even call other wildcards, allowing for recursion
__fruit_exotic__
```

These two powerful methods can be combined to build very dynamic prompts. Here's a simple example of what can be done:

**Example Input:** ```masterpiece, {2$$__shot__|__canvas__}, __scene_forest__, __quality__```

**Example Output:** ```masterpiece, blue canvas, wideshot, magnificent forest with willow trees with a patch of grass and daffodils, blueberry bush, high-quality, highres```


To see what's going on here, take a look at how dynamic prompts handles unwrapping these nested brackets and wildcards:

**Processing Stage 1:** ```masterpiece, __color__ canvas, wideshot, __adj__ forest with {2-3$$ and $$__plants__|__trees__|__grass__}, high-quality, highres```

**Processing Stage 2:** ```masterpiece, blue canvas, wideshot, __wonderful__ forest with willow trees and a patch of grass and __flowers__, __bush__, high-quality, highres```

Processing Stage 3 is not required because everything has been unwrapped.

Notice how wildcards can be nested within wildcards. It's all up to how you structure your bracket options and wildcards.

Here's an alternate Result Example when using that very same input example: ```masterpiece, closeup shot, pink canvas, excellent shaded forest with cherry-blossom trees, rocks along a cliffside, shaded forest, godrays, gravel path leading to a cave, riverbed, colorgraded, best quality```

### 🔢 Multiple Choices within Brackets
Multiple selections can be made using this syntax:
```
{5$$__fruit__}
{2-4$$__animal__|__color__}
```
Line 1 could be read as instruction: ```pull 5 random lines from fruit.txt```
Line 2 could be read as instruction: ```pull 2 to 4 random lines from animal.txt and bird.txt```

Example Result:
```
apple, mango, kiwi, orange, banana
cat, green, dog
```

If you don't want a comma and space between each selection, you can use your own custom separator using the following syntax:
```
{3-5$$ $$__fruit__}
{3$$ and $$__animal__}
```

Example Result:
```
apple banana kiwi strawberry
sheep and cat and dog
```

### 📁 Wildcard Random Selection and Subfolders

Wildcards can be even more randomized, by utilizing the * symbol. Here's an example. Say you have the following folder structure within /wildcards/:

```
lighting.txt
lighting_dim.txt
lighting_bright.txt
```

By calling ```__lighting*__``` it will pick one of those three files to draw a prompt from. Furthermore, if you want to bypass the original ```lighting.txt```, you can type ```__lighting_*__``` to ensure that only the two latter are selected. This function can be read as ```select any wildcard in this folder that starts with "lighting_"```

Wildcards can also be be nested in subfolders. ```/wildcards/environments/cave.txt``` can be called with ```__environments/cave__```. One primary advantage of this is that it can help with organization for certain themes. Not only that, using a * expression works here, but restricts to only that folder. ```__environments/*__``` will select *any* wildcard in the /environments/ folder.
Yes, this also means you can use the wildcard ```__*__```. I don't recommend this unless you prefer chaos.

Yes, the possibilities are endless. And these are just the basics of what can be done with dynamic prompts.

> This is the extend of what is currently supported *as of August 16, 2025*.

</details>



# New Features and Nodes

## Fixes & Changes

### Wildcards Refresh Instantly
No more having to restart ComfyUI every time you make a change to wildcards.

### Lora tags with "weird__underscores" no longer break syntax!

Dynamic prompts no longer completely derail simply because of an unfortunate naming convention by a lora. *cough cough*. So `<lora:coolest__lora__ever__:1.0>` will not break things.

## Separator Syntax

Separators can now be generated with dynamic prompts as well. Example:

```{4$$ __and__ $$bob|bertha|benny|bella}``` -> ```bertha with benny and bob plus bella```

Let's say that **and.txt** contains the following:
```
and
with
or
```

Then we use that wildcard as the separator token for a bracket wildcard:
```
{3-4$$ __and__ $$A|B|C|D|E}
```

example outputs:
```
A or E and B
C and D with B or A
B with C and D
```

This opens up possibilities for expanding bracket prompts. ```{2-3$${,| }$$this|works|too}```


**Chance Weights**

A very simple chance weighting system is included.
Here's a `chance.txt` wildcard example:

```
#
%80% common
%10% uncommon
rare  # default is 1
%0.1% ultrarare
```

### Additional Notes

* Bracket and file wildcards support **recursive nesting**.
* You can specify **ranges**, **custom separators**, and even **wildcard separators**.
* Comments in wildcard files are supported using `#` at the start of a line.
* Optional **weights** can be added to lines using `%number%` anywhere in the line to influence selection probability.
* Escaped percent signs (`\%`) are preserved in the output, if you're so inclined to use them.

---



## 📦 Wildcard Rewrap
Wildcard Rewrap is a new node which can be thought of as the inverse of Prompt Generation. Encapsulates keywords with a wildcard file they exist in. This allows for semantic driven dynamic prompting and even more brainstorming.
Example Input:
```
table and color apple
```
Example Output:
```
__furniture__ and __color__ __fruit__
```

The purpose of this node is to allow you to write with natural language, then wrapping it in a dynamic and creative way.

> Note: Rewrap pre-caches for faster lookups on startup. So if changes are made to wildcards, you'll have to restart.


## 🔁 Wildcard Replace
Acts as a standard String Replace function, with a twist. The search string and replace string both accept wildcards.

**String** - The input string to process
```
the quick brown fox jumped over the lazy dog
```

**Search** - performs multiple searches based on new lines
```
fox
dog
```

**Replace** - calculates dynamic prompts for each replacement action, this can be brackets or wildcards
```
{1-2$$ and $$__animal__}
```

Example Result:
```
the quick brown cow and pig jumped over the lazy cat
```




  - Can be used as a regular Search and Replace
  - Allows for multi-line inputs for searching, allowing for many different keywords to be swapped out in one go.

# String Utilities

>These are simple but useful nodes that apply to any prompt, and can serve as a powerful post-processing for dynamic prompts.

## ♻️ **Shuffle Tags**
  - A very simple shuffler which can randomize ordering of a prompt, a limit can be set
## ♻️ **Shuffle Tags (Advanced)**
  - Same as above, but can follow various algorithms such as "walk" to allow tags to travel, utilize decay, and many other things.
## 🧹 **Cleanup Tags**
  - Sometimes, dynamic prompts gets messy. This little guy can help clean up broken prompts by removing empty tags, extra whitespace, and even remove straight-up remove lora tags that failed to process by other nodes.
## 🟰 **Normalize Lora Tags**
  - Worry less about the oversaturation of lora tags with this node which helps normalize the values automatically.
  - Positive and Negative values can be assigned independently or combined.
  - Lora Tag Parser. I recommend: [Lora Tag Loader by badjeff](https://github.com/badjeff/comfyui_lora_tag_loader)
## **String Merger**
  - Has a (4) version and a (12) version
  - Combines strings separated with a new-line.




# 💡 Tricks & Tips


## Randomized Lora Weights
A neat trick you can do is create a wildcard as the weight of a lora. This means you can establish randomized lora weights.
This works well if you're using [Lora Tag Loader](#Links).

rlow.txt:
```
# Random Low Weights
0.05
0.1
0.15
0.2
0.25
0.3
```

Then I run this through the prompt generator:
```
<lora:funny_dog:__rlow__>
```
This allows for wildcards and prompts to handle loras for you.
Consider combining this with the Lora Tag Normalizer.

# Links

  ### [Custom Scripts by pythongosssss](https://github.com/pythongosssss/ComfyUI-Custom-Scripts)
  Provides a handful of useful nodes. Honestly, a must-have. These are ones I use often:
  - Show Text (simple and practically essential)
  - String Function (for appending or replacing strings)
  - Image Feed (for displaying results)
  ### [Lora Tag Loader by badjeff](https://github.com/badjeff/comfyui_lora_tag_loader)
  This loads loras using the classic ```<lora:sharpness_enhancer:1.0>``` syntax, providing a model and clip node, as well as preserving the string. Works excellently with dynamic prompts.



## Disclaimer

I do not intend to recreate Dynamic Prompts one-to-one. Rather, I'll be utilizing the core concepts and syntax as a starting point.

Python is not my primary programming language. And although the code words, that doesn't make it optimized. Take that for what you will.

I also have no plans to adapt this to A1111 / Forge.